namespace WitcherRevival.Server.Net;

/// <summary>
/// The texts hook.js gives the game (its "texts" stage fetches GET /revival/texts once at start and answers
/// I2.Loc.LocalizationManager.GetTranslation with them), following the dashboard's settings: a monster's bestiary
/// "Occurrence" line when the wiki's tags are in use (built from the game's own phrases, so one string serves every
/// language), each trinket's bonus line and attack modifier name while trinket bonuses are on, the weather items' names and
/// descriptions (they reuse the icons of unused consumables, whose own texts they replace), a pack's Open texts while packs
/// open from the inventory, a line on the pack's description while it holds more than herbs and roots, and a line on each
/// oil's description while oils keep the original sum (combat.oilsMultiply off). Those are by language (GameTexts):
/// {"en": …, "pl": …}. "settings" carries the Tuning values hook.js applies in the game (WorldTuning.GameSettings).
/// </summary>
public static class ClientTexts
{
    /// <summary>The INFO_2 line of a monster's bestiary entry for [tags], as the client writes it (term references).</summary>
    public static string OccurrenceLine(IEnumerable<string> tags) =>
        "[0{**UI/PANELS/BESTIARY/OCCURANCE**}0]: " + string.Concat(tags.Select(tag => $"**MONSTERS/OCCURANCE/{tag}**\n"));

    // Not game terms: hook.js uses them for a pack's buttons and its count window's question while packs open from the inventory.
    public const string OpenPackButton = "REVIVAL/OPEN_PACK", OpenPackHeader = "REVIVAL/OPEN_PACK_HEADER";

    public static object Build()
    {
        var replace = new Dictionary<string, object>();
        var append = new Dictionary<string, object>();
        if (WorldTuning.Current.On(WorldTuning.WikiOccurrences))
            foreach (var species in WorldBestiary.All.Where(s => s.ClientTags is { } client && !client.SequenceEqual(s.Tags)))
                replace[$"MONSTERS/DESCRIPTIONS/{species.Slug.ToUpperInvariant()}/INFO_2"] = OccurrenceLine(species.Tags);
        if (WorldTuning.Current.On(WorldTuning.TrinketBuffs))
        {
            foreach (var (term, text) in TrinketBuffs.Texts()) append[term] = text;
            foreach (var (term, text) in TrinketBuffs.ModifierNames()) replace[term] = text;
        }
        foreach (var item in Consumables.All.Where(c => c.Weather is not null))
        {
            var (name, description) = GameTexts.Charms[item.Id];
            replace[$"ITEMS/NAMES/CONSUMABLES/{item.Slug.ToUpperInvariant()}"] = name;
            replace[$"ITEMS/DESCRIPTIONS/CONSUMABLES/{item.Slug.ToUpperInvariant()}"] = description;
            replace[$"NOTIFICATIONS/EFFECT/{item.ModifierSlug.ToUpperInvariant()}"] = name;
        }
        if (WorldTuning.Current.On(WorldTuning.OpenPacks))
        {
            replace[OpenPackButton] = GameTexts.Open;
            replace[OpenPackHeader] = GameTexts.OpenHeader;
        }
        if ((WorldTuning.Current.Rewards.PackPool ?? []).Any(row => row.Weight > 0 &&
            !(row.Kind == ItemKinds.Ingredients && row.Id is Economy.Herba or Economy.Radix)))
            append["ITEMS/DESCRIPTIONS/PACKS/PACK_HERBALIST"] = GameTexts.RarerFinds.ToDictionary(p => p.Key, p => "\n" + p.Value);
        if (!WorldTuning.Current.On(WorldTuning.OilsMultiply))
            foreach (var oil in Reconstruction.Oils)
                append[$"ITEMS/DESCRIPTIONS/OILS/{oil.Slug.ToUpperInvariant()}"] = GameTexts.OilBaseDamage.ToDictionary(p => p.Key, p => "\n" + p.Value);
        var settings = WorldTuning.GameSettings.ToDictionary(key => key, WorldTuning.Current.Get);
        return new { replace, append, settings };
    }
}
