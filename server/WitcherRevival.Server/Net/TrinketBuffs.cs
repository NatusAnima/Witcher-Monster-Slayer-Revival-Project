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
    /// attack against that family by the same percentage (player modifier [Modifier]).</summary>
    public sealed record Buff(int Trinket, string Slug, string Name, Kind Kind, int Amount, string Text, int? Family = null,
        int? Modifier = null);

    // Families: 1 necrophage, 2 draconid, 6 relict, 7 specter, 11 cursed (monster_families).
    public static readonly IReadOnlyList<Buff> All = new Buff[]
    {
        new(20001, "trophy_lizard_slayer", "Lizard Slayer", Kind.Exp, 20, "+20% experience and +20% attack against draconids", 2, 921),
        new(20002, "trophy_in_forest_dark", "In Forest Dark", Kind.Herbs, 15, "+15% herbs"),
        new(20003, "trophy_legendary_monster_slayer", "Legendary Monster Slayer", Kind.NestGold, 100, "+100% orens from nemeta"),
        new(20004, "trophy_mushroom_trophy_1", "The Champion", Kind.Herbs, 100, "+100% herbs"),
        new(20005, "trophy_mushroom_trophy_2", "The Vice-Champion", Kind.Herbs, 60, "+60% herbs"),
        new(20006, "trophy_mushroom_trophy_3", "The Vice-Vice Champion", Kind.Herbs, 40, "+40% herbs"),
        new(20007, "trophy_mushroom_trophy_4", "Enough for a Stew", Kind.Herbs, 25, "+25% herbs"),
        new(20008, "trophy_mushroom_trophy_5", "Good Intentions", Kind.Herbs, 15, "+15% herbs"),
        new(20009, "trophy_broken_sword", "The Striga's Demise", Kind.Exp, 20, "+20% experience and +20% attack against cursed ones", 11, 922),
        new(20010, "trophy_frightener_claw", "The Frightener of Dol Tirthana", Kind.Exp, 10, "+10% experience from fights"),
        new(20011, "trophy_from_vizima_to_beauclair", "From Vizima to Beauclair", Kind.Slots, 200, "+200 inventory slots"),
        new(20012, "trophy_disturbed_the_water", "Disturbed the Water", Kind.Exp, 20, "+20% experience and +20% attack against necrophages", 1, 923),
        new(20013, "trophy_fear_no_more", "Fear no More", Kind.Exp, 20, "+20% experience and +20% attack against specters", 7, 924),
        new(20014, "trophy_smashed_figurine", "Inner Beauty", Kind.Ingredients, 10, "+10% ingredients from fights"),
        new(20015, "trophy_stone_heart", "Follow Your Heart", Kind.Exp, 5, "+5% experience from fights"),
        new(20016, "trophy_flower_bottle", "Brother in Arms", Kind.Ingredients, 10, "+10% ingredients from fights"),
        new(20017, "trophy_used_candles", "Something More", Kind.Ingredients, 15, "+15% ingredients from fights"),
        new(20018, "trophy_child_drawing", "Cursebreaker", Kind.Exp, 10, "+10% experience and +10% attack against cursed ones", 11, 925),
        new(20019, "trophy_blacksmith_hammer", "The Werewolf's Lot", Kind.Slots, 50, "+50 inventory slots"),
        new(20020, "trophy_blacksmith_hammer_bloody", "The Werewolf's Lot", Kind.Slots, 50, "+50 inventory slots"),
        new(20021, "trophy_mushroom_leshen", "Mushroom Sentinel", Kind.Exp, 20, "+20% experience and +20% attack against relicts", 6, 926),
        new(20022, "trophy_toy_sword", "Dehael's Pride", Kind.NestGold, 25, "+25% orens from nemeta"),
        new(20023, "trophy_toy_sword_bloody", "Dehael's Pride", Kind.NestGold, 25, "+25% orens from nemeta"),
        new(20024, "trophy_journal_season_01", "Strigas, Lihos, and Frighteners", Kind.Station, 1, "a second alchemy station that never wears out"),
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

    /// <summary>The line a trinket's description gains in the game (hook.js texts).</summary>
    public static IReadOnlyDictionary<string, string> Texts() => All.ToDictionary(
        b => $"ACHIEVEMENTS/DESCRIPTIONS/{b.Slug.ToUpperInvariant()}", b => "\nBonus: " + b.Text);

    /// <summary>The effects panel's names of the attack modifiers (NOTIFICATIONS/EFFECT/&lt;SLUG&gt;; the trinkets' names are
    /// the client's English ACHIEVEMENTS/NAMES/&lt;SLUG&gt;).</summary>
    public static IReadOnlyDictionary<string, string> ModifierNames() =>
        All.Where(b => b.Modifier is not null).ToDictionary(b => $"NOTIFICATIONS/EFFECT/{b.Slug.ToUpperInvariant()}",
            b => $"{b.Name}: {b.Text[(b.Text.IndexOf(" and ", StringComparison.Ordinal) + 5)..]}");
}
