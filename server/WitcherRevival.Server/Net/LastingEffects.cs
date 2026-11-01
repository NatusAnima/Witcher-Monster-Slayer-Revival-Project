namespace WitcherRevival.Server.Net;

/// <summary>
/// Potions and oils that last (Tuning combat.lastingMinutes, Revival 60; 0, the original, keeps them to one fight). A potion or
/// oil spent on a fight (UseOilPotions 89, PrepareToCombat 10) also becomes a player modifier with that item's own effects,
/// which the game applies to every fight while it lasts (PlayerModifiersModule.GetActiveEffects 0x18BF4A8) and the map's
/// effects panel shows with the time left. As many potions as the potion slots (Economy.PotionCapacity), a new one replacing
/// the one taken first; one oil, a new one replacing it. The same potion again starts its time again.
/// The fight it was taken for already has it from its preparation, so PlayerService keeps those out of the modifiers the game
/// has until that fight ends.
/// </summary>
public static class LastingEffects
{
    /// <summary>A lasting item's modifier id is this plus the item's id (potions 2xx, oils 3xx).</summary>
    public const int Base = 10000;

    public static bool IsPotion(int modifier) => modifier - Base is >= 200 and < 300;
    public static bool IsOil(int modifier) => modifier - Base is >= 300 and < 400;

    /// <summary>The player_modifiers rows: one per potion and oil (slug "lasting_" and the item's slug).</summary>
    public static IEnumerable<(int Id, string Slug)> ModifierRows() =>
        Reconstruction.Potions.Select(p => (Base + p.Id, "lasting_" + p.Slug))
            .Concat(Reconstruction.Oils.Select(o => (Base + o.Id, "lasting_" + o.Slug)));

    /// <summary>The player_modifier_to_effect rows: each item's own effects (potion_to_effect, oil_to_effect) on its modifier.</summary>
    public static IEnumerable<Reconstruction.ItemEffect> EffectRows() =>
        Reconstruction.PotionEffects().Concat(Reconstruction.OilEffects()).Select(e => e with { ItemId = Base + e.ItemId });

    /// <summary>The effects panel's names (NOTIFICATIONS/EFFECT/LASTING_&lt;slug&gt;), each the game's own term for the item's
    /// name, which hook.js looks up (ClientTexts' aliases; the panel shows a "**term**" reference as it is).</summary>
    public static IEnumerable<(string Term, string GameTerm)> Names() =>
        Reconstruction.Potions.Select(p => (p.Slug, "POTIONS")).Concat(Reconstruction.Oils.Select(o => (o.Slug, "OILS")))
            .Select(x => ($"NOTIFICATIONS/EFFECT/LASTING_{x.Slug.ToUpperInvariant()}", $"ITEMS/NAMES/{x.Item2}/{x.Slug.ToUpperInvariant()}"));

    /// <summary>The modifiers after [potions] and [oil] (-1: none) are taken at [now] for [minutes]: [live] without the lasting
    /// items they replace, and theirs.</summary>
    public static List<LocalProfileStore.ModifierState> Taken(IReadOnlyList<LocalProfileStore.ModifierState> live,
        IReadOnlyList<int> potions, int oil, int capacity, int now, int minutes)
    {
        var taken = potions.Select(p => Base + p).Concat(oil == -1 ? [] : [Base + oil]).ToHashSet();
        var kept = live.Where(m => !taken.Contains(m.Id) && !(oil != -1 && IsOil(m.Id))).ToList();
        var fresh = taken.Select(id => new LocalProfileStore.ModifierState(id, now, now + minutes * 60)).ToList();
        // potions beyond the slots go, the one taken first first
        int over = kept.Count(m => IsPotion(m.Id)) + fresh.Count(m => IsPotion(m.Id)) - capacity;
        foreach (var old in kept.Where(m => IsPotion(m.Id)).OrderBy(m => m.Start).Take(Math.Max(0, over)).ToList()) kept.Remove(old);
        return [.. kept, .. fresh];
    }
}
