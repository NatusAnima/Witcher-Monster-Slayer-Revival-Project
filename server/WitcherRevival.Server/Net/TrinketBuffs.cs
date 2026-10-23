namespace WitcherRevival.Server.Net;

/// <summary>
/// The bonuses trinkets give (Revival; Tuning trinkets.buffs, Vanilla none). The table lives here because a trinket row
/// cannot gain fields (the task catalogue's identities are persisted). A bonus comes from the trinkets a profile has
/// (TaskEngine.State.Achievements), so the client cannot remove it and trinkets earned earlier count at once. Bonuses
/// of one kind add up. Each trinket's description in the game gains a "Bonus:" line (hook.js texts, served by the
/// server), and an attack bonus against a family shows in the effects panel as a permanent modifier.
/// </summary>
public static class TrinketBuffs
{
    public enum Kind { Herbs, Exp, Ingredients, NestGold, Slots, Station }

    /// <summary>[Family]: the monster family a fight bonus applies to (null: every fight); such a bonus also raises the
    /// attack against that family by the same percentage (player modifier [Modifier]). Its words: <see cref="Line"/>.</summary>
    public sealed record Buff(int Trinket, string Slug, Kind Kind, int Amount, int? Family = null, int? Modifier = null);

    // Families: 1 necrophage, 2 draconid, 6 relict, 7 specter, 11 cursed (monster_families).
    public static readonly IReadOnlyList<Buff> All = new Buff[]
    {
        new(20001, "trophy_lizard_slayer", Kind.Exp, 20, 2, 921),
        new(20002, "trophy_in_forest_dark", Kind.Herbs, 15),
        new(20003, "trophy_legendary_monster_slayer", Kind.NestGold, 100),
        new(20004, "trophy_mushroom_trophy_1", Kind.Herbs, 100),
        new(20005, "trophy_mushroom_trophy_2", Kind.Herbs, 60),
        new(20006, "trophy_mushroom_trophy_3", Kind.Herbs, 40),
        new(20007, "trophy_mushroom_trophy_4", Kind.Herbs, 25),
        new(20008, "trophy_mushroom_trophy_5", Kind.Herbs, 15),
        new(20009, "trophy_broken_sword", Kind.Exp, 20, 11, 922),
        new(20010, "trophy_frightener_claw", Kind.Exp, 10),
        new(20011, "trophy_from_vizima_to_beauclair", Kind.Slots, 200),
        new(20012, "trophy_disturbed_the_water", Kind.Exp, 20, 1, 923),
        new(20013, "trophy_fear_no_more", Kind.Exp, 20, 7, 924),
        new(20014, "trophy_smashed_figurine", Kind.Ingredients, 10),
        new(20015, "trophy_stone_heart", Kind.Exp, 5),
        new(20016, "trophy_flower_bottle", Kind.Ingredients, 10),
        new(20017, "trophy_used_candles", Kind.Ingredients, 15),
        new(20018, "trophy_child_drawing", Kind.Exp, 10, 11, 925),
        new(20019, "trophy_blacksmith_hammer", Kind.Slots, 50),
        new(20020, "trophy_blacksmith_hammer_bloody", Kind.Slots, 50),
        new(20021, "trophy_mushroom_leshen", Kind.Exp, 20, 6, 926),
        new(20022, "trophy_toy_sword", Kind.NestGold, 25),
        new(20023, "trophy_toy_sword_bloody", Kind.NestGold, 25),
        new(20024, "trophy_journal_season_01", Kind.Station, 1),
    };

    /// <summary>The permanent station's instance id (the shop's stations count up from the basic one, 1).</summary>
    public const long StationInstance = 1_020_024;

    /// <summary>The bonuses a profile has now (none when the dashboard switches them off).</summary>
    public static IEnumerable<Buff> Of(LocalProfileStore.PlayerState? player) =>
        player?.Tasks?.Achievements is { } earned && WorldTuning.Current.On(WorldTuning.TrinketBuffs)
            ? All.Where(b => earned.ContainsKey(b.Trinket)) : [];

    /// <summary>The summed percentage (or slots) of one kind; a fight bonus counts when it is for every fight or for
    /// [family].</summary>
    public static int Amount(LocalProfileStore.PlayerState? player, Kind kind, int? family = null) =>
        Of(player).Where(b => b.Kind == kind && (b.Family is null || b.Family == family)).Sum(b => b.Amount);

    public static bool Station(LocalProfileStore.PlayerState? player) => Of(player).Any(b => b.Kind == Kind.Station);

    /// <summary>The permanent modifiers of the attack bonuses a profile has (expiry: never).</summary>
    public static IEnumerable<LocalProfileStore.ModifierState> Modifiers(LocalProfileStore.PlayerState? player) =>
        Of(player).Where(b => b.Modifier is not null).Select(b => new LocalProfileStore.ModifierState(b.Modifier!.Value,
            player!.Tasks!.Achievements[b.Trinket], -1));

    /// <summary>Static rows of the attack modifiers: ImproveAttacksAgainst&lt;Family&gt; (effect 28 + family), the effect
    /// the family oils use, applied when the fight has its target (Reconstruction.FightStart).</summary>
    public static IEnumerable<(int Modifier, string Slug, int Effect, int Power)> ModifierRows() =>
        All.Where(b => b.Modifier is not null).Select(b => (b.Modifier!.Value, b.Slug, 28 + b.Family!.Value, b.Amount));

    /// <summary>A bonus in words, by language (GameTexts).</summary>
    public static Dictionary<string, string> Line(Buff b) => b.Kind switch
    {
        Kind.Herbs => GameTexts.Format(GameTexts.Herbs, b.Amount),
        Kind.NestGold => GameTexts.Format(GameTexts.NestGold, b.Amount),
        Kind.Exp when b.Family is { } family => GameTexts.Format(GameTexts.FamilyExp, b.Amount, GameTexts.Against[family]),
        Kind.Exp => GameTexts.Format(GameTexts.FightExp, b.Amount),
        Kind.Ingredients => GameTexts.Format(GameTexts.Ingredients, b.Amount),
        Kind.Slots => GameTexts.Format(GameTexts.Slots, b.Amount),
        _ => GameTexts.Station,
    };

    /// <summary>The line a trinket's description gains in the game (hook.js texts), by language.</summary>
    public static IReadOnlyDictionary<string, Dictionary<string, string>> Texts() => All.ToDictionary(
        b => $"ACHIEVEMENTS/DESCRIPTIONS/{b.Slug.ToUpperInvariant()}",
        b => Line(b).ToDictionary(p => p.Key, p => "\n" + GameTexts.Bonus[p.Key] + p.Value));

    /// <summary>The effects panel's names of the attack modifiers (NOTIFICATIONS/EFFECT/&lt;SLUG&gt;), by language: the trinket's
    /// name and its attack bonus.</summary>
    public static IReadOnlyDictionary<string, Dictionary<string, string>> ModifierNames() =>
        All.Where(b => b.Modifier is not null).ToDictionary(b => $"NOTIFICATIONS/EFFECT/{b.Slug.ToUpperInvariant()}",
            b => GameTexts.Format(GameTexts.AttackName, b.Amount, GameTexts.Against[b.Family!.Value], GameTexts.TrinketNames[b.Slug]));
}
