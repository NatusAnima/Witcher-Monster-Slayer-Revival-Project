using System.Text.Json;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    public sealed record PresetCreate(string From, string Name);
    public sealed record PresetRename(string Name);
    public sealed record PresetActivate(string Preset);
    public sealed record RewardsWrite(string Revision, RewardTables Rewards);

    /// <summary>The player's own numbers (WorldTuning) in presets: Revival and Vanilla built in, the player's own ones in
    /// world/presets. Changing a built-in preset saves a copy of the player's. Rewards (RewardTables) belong to the preset too.
    /// Every change leaves a receipt and a backup of the file it replaced.</summary>
    private void MapTuningRoutes(WebApplication app)
    {
        string TuningPath() => Path.Combine(worldRoot, "tuning.json");
        string Revision() => File.Exists(TuningPath()) ? Digest(File.ReadAllBytes(TuningPath())) : "missing";
        object Presets() => world.Tuning.Presets().Select(p => new { id = p.Id, name = p.Name, builtIn = p.BuiltIn });
        T Checked<T>(Func<T> read) { try { return read(); } catch (InvalidDataException e) { throw new Refusal(400, e.Message); } }

        // Writes a file under a receipt, backing up what it replaces (deleted presets too).
        Receipt Write(string path, byte[]? bytes, string action, string effect)
        {
            byte[]? before = File.Exists(path) ? File.ReadAllBytes(path) : null;
            var receipt = NewReceipt(action, Path.GetFileName(path), "accepted", before is null ? "missing" : Digest(before),
                bytes is null ? "deleted" : Digest(bytes), effect);
            SaveReceipt(receipt);
            try
            {
                if (before is not null) Atomic(Path.Combine(root, "backups", receipt.Id + ".bin"), before);
                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                if (bytes is null) File.Delete(path); else Atomic(path, bytes);
                receipt = receipt with { Outcome = "applied" };
                SaveReceipt(receipt);
                return receipt;
            }
            catch { SaveReceipt(receipt with { Outcome = "failed" }); throw; }
        }
        Receipt Activate(WorldTuning.Preset preset, string effect)
        {
            var receipt = Write(TuningPath(), WorldTuning.Serialize(preset.Id, preset.Values), "tuning", effect);
            world.Tuning.Refresh();
            return receipt;
        }
        // The active preset as the player's own one: itself, or a new copy when it is built in.
        WorldTuning.Preset Owned(string? name)
        {
            var active = world.Tuning.FindPreset(world.Tuning.ActivePreset) ?? WorldTuning.RevivalPreset();
            return active.BuiltIn
                ? active with { Id = world.Tuning.NewPresetId(), Name = WorldTuning.CheckName(name ?? $"{active.Name} (my copy)"), BuiltIn = false }
                : active;
        }
        void CheckRevision(string expected)
        {
            if (expected != Revision()) throw new Refusal(409, "This resource changed since it was opened. Refresh and review your changes before retrying.");
        }
        object State() => new { revision = Revision(), preset = world.Tuning.ActivePreset, presets = Presets(),
            values = world.Tuning.Effective(), definitions = WorldTuning.Settings };

        app.MapGet("/api/tuning", () =>
        {
            lock (gate) { world.Tuning.Refresh(); return Results.Json(State()); }
        });
        app.MapPut("/api/tuning", async (HttpRequest request) =>
        {
            var write = await Body<DocumentWrite>(request);
            lock (gate)
            {
                CheckRevision(write.Revision);
                var preset = Owned(write.Document.TryGetProperty("name", out var n) ? n.GetString() : null);
                var values = Checked(() => WorldTuning.Parse(write.Document, strict: true, preset.Values));
                preset = preset with { Values = values };
                Write(world.Tuning.PresetPath(preset.Id)!, WorldTuning.SerializePreset(preset), "tuning-preset",
                    $"The preset \"{preset.Name}\" is saved.");
                var receipt = Activate(preset, "The settings are saved and each takes effect as its line says; no restart is needed.");
                return Results.Json(new { receipt, revision = Revision(), preset = preset.Id });
            }
        });
        app.MapPost("/api/tuning/presets", async (HttpRequest request) =>
        {
            var create = await Body<PresetCreate>(request);
            lock (gate)
            {
                var source = world.Tuning.FindPreset(create.From) ?? throw new Refusal(404, "That preset does not exist.");
                var preset = source with { Id = world.Tuning.NewPresetId(), Name = Checked(() => WorldTuning.CheckName(create.Name)), BuiltIn = false };
                Write(world.Tuning.PresetPath(preset.Id)!, WorldTuning.SerializePreset(preset), "tuning-preset",
                    $"The preset \"{preset.Name}\" is created from \"{source.Name}\".");
                Activate(preset, $"The preset \"{preset.Name}\" is in use.");
                return Results.Json(State());
            }
        });
        app.MapPut("/api/tuning/presets/{id}", async (HttpRequest request, string id) =>
        {
            var rename = await Body<PresetRename>(request);
            lock (gate)
            {
                var preset = world.Tuning.FindPreset(id) ?? throw new Refusal(404, "That preset does not exist.");
                if (preset.BuiltIn) throw new Refusal(409, "Revival and Vanilla keep their names; make a copy to have your own.");
                preset = preset with { Name = Checked(() => WorldTuning.CheckName(rename.Name)) };
                Write(world.Tuning.PresetPath(id)!, WorldTuning.SerializePreset(preset), "tuning-preset", $"The preset is renamed \"{preset.Name}\".");
                world.Tuning.Refresh();
                return Results.Json(State());
            }
        });
        app.MapDelete("/api/tuning/presets/{id}", (string id) =>
        {
            lock (gate)
            {
                var preset = world.Tuning.FindPreset(id) ?? throw new Refusal(404, "That preset does not exist.");
                if (preset.BuiltIn) throw new Refusal(409, "Revival and Vanilla are always there.");
                bool wasActive = world.Tuning.ActivePreset == id;
                Write(world.Tuning.PresetPath(id)!, null, "tuning-preset", $"The preset \"{preset.Name}\" is deleted (its file is in the backups).");
                if (wasActive) Activate(WorldTuning.RevivalPreset(), "Revival is in use again.");
                world.Tuning.Refresh();
                return Results.Json(State());
            }
        });
        app.MapPut("/api/tuning/active", async (HttpRequest request) =>
        {
            var choice = await Body<PresetActivate>(request);
            lock (gate)
            {
                var preset = world.Tuning.FindPreset(choice.Preset) ?? throw new Refusal(404, "That preset does not exist.");
                Activate(preset, $"The preset \"{preset.Name}\" is in use; each setting takes effect as its line says.");
                return Results.Json(State());
            }
        });

        // The Rewards page: the active preset's reward tables, the endings it lists, the items they may hold and the shop's
        // bundles (their contents and Vanilla prices) for the price table.
        object Catalog() => new
        {
            groups = RewardTables.Groups,
            items = RewardItems().Select(i => new { kind = i.Kind, id = i.Id, slug = i.Slug }),
            levels = Reconstruction.MaxLevel,
            shop = Economy.Bundles.Where(b => b.InAppPrice is null).Select(b => new
            {
                id = b.Id, tab = b.Tab, group = b.Group, oneTime = b.OneTime, vanilla = b.GoldPrice,
                items = b.Items.Select(i => new { slug = SlugOf(i.Type, i.Item), amount = i.Amount }),
            }),
        };
        app.MapGet("/api/rewards", () =>
        {
            lock (gate)
            {
                world.Tuning.Refresh();
                var active = world.Tuning.FindPreset(world.Tuning.ActivePreset) ?? WorldTuning.RevivalPreset();
                return Results.Json(new { revision = Revision(), preset = active.Id, name = active.Name, builtIn = active.BuiltIn,
                    rewards = world.Tuning.Rewards, vanilla = RewardTables.Vanilla, revival = RewardTables.Revival, catalog = Catalog() },
                    RewardTables.Json);
            }
        });
        app.MapPut("/api/rewards", async (HttpRequest request) =>
        {
            var write = JsonSerializer.Deserialize<RewardsWrite>(await Bytes(request, 1024 * 1024), RewardTables.Json)
                ?? throw new InvalidDataException();
            Checked(() => { RewardTables.Validate(write.Rewards); return 0; });
            lock (gate)
            {
                CheckRevision(write.Revision);
                var preset = Owned(null) with { Rewards = write.Rewards };
                Write(world.Tuning.PresetPath(preset.Id)!, WorldTuning.SerializePreset(preset), "rewards",
                    $"The rewards of \"{preset.Name}\" are saved; quests, tasks, levels and packs pay them from now on, and the " +
                    "shop's prices apply from the next server and game start.");
                var receipt = Activate(preset, $"The preset \"{preset.Name}\" is in use.");
                return Results.Json(new { receipt, revision = Revision(), preset = preset.Id, name = preset.Name });
            }
        });
    }

    /// <summary>The slug the dashboard shows for a shop bundle's element ("bag" for inventory slots).</summary>
    private static string SlugOf(int type, int item) => type switch
    {
        Economy.TypeArmor => Reconstruction.ArmorById(item)?.Slug,
        Economy.TypeSword => Reconstruction.SwordById(item)?.Slug,
        Economy.TypeBrewer => Economy.Brewers.FirstOrDefault(b => b.Id == item)?.Slug,
        Economy.TypeBag => "bag",
        _ => RewardItems().FirstOrDefault(i => i.Kind == Economy.KindOf(type) && i.Id == item).Slug,
    } ?? $"{type}:{item}";

    /// <summary>Every item a reward may hold, with the slug the dashboard shows.</summary>
    private static IEnumerable<(string Kind, int Id, string Slug)> RewardItems() =>
        Reconstruction.Potions.Select(p => (ItemKinds.Potions, p.Id, p.Slug))
            .Concat(Reconstruction.Oils.Select(o => (ItemKinds.Oils, o.Id, o.Slug)))
            .Concat(new[] { (ItemKinds.Bombs, Reconstruction.BasicBombId, "bomb_basic") })
            .Concat(Reconstruction.ExtraBombs.Select(b => (ItemKinds.Bombs, b.Id, b.Slug)))
            .Concat(new[] { (ItemKinds.SensesPotions, Economy.Falcon, "senses_potion_falcon") })
            .Concat(WorldNests.Lures.Select(l => (ItemKinds.Lures, l.Id, l.Slug)))
            .Concat(SummonScrolls.All.Select(s => (ItemKinds.SummoningScrolls, s.Id, s.Slug)))
            .Concat(Consumables.All.Select(c => (ItemKinds.Consumables, c.Id, c.Slug)))
            .Concat(Reconstruction.Swords.Select(s => (ItemKinds.Swords, s.Id, s.Slug)))
            .Concat(Reconstruction.Armors.Select(a => (ItemKinds.Armors, a.Id, a.Slug)))
            .Concat(Economy.Ingredients.Select(i => (ItemKinds.Ingredients, i.Id, i.Slug)));
}
