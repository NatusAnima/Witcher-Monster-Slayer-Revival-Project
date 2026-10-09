namespace WitcherRevival.Server.Net;

/// <summary>Explicit LAB policy, not recovered historical drop odds, numeric pack ids or reward quantities.
/// Pack type 15 and the herbalist slug are observed in the original client. Numeric id 1 is reconstructed.</summary>
public static class SocialPolicy
{
    /// <summary>The inventory space the client counts as used (PlayerInventory.GetAllItemsInEquipmentQuantity); the
    /// capacity is Economy.BagSize.</summary>
    public static long Occupied(LocalProfileStore.PlayerState player)
    {
        var brewers = player.Brewers ?? [];
        long stacks = player.Items.Values.SelectMany(items => items.Values).Sum(count => (long)Math.Max(0, count));
        // EnsureBrewers always exposes the unlimited basic station, even before it has been saved.
        long stations = brewers.Count + (brewers.Any(b => b.InstanceId == Economy.BasicBrewerInstance) ? 0 : 1);
        return stacks + stations + brewers.Count(b => b.WorkingRecipe >= 0);
    }

    /// <summary>Call inside the successful combat's existing UpdatePlayer callback, after kills are incremented.
    /// The ordinary combat replay guard protects this same saved revision. Returns the pack id for CombatEnd.</summary>
    public static LocalProfileStore.PlayerState AwardCombatPack(IConfiguration cfg,
        LocalProfileStore.PlayerState before, LocalProfileStore.PlayerState after, out int pack)
    {
        pack = 0;
        int every = cfg.GetValue("Social:GiftEveryWins", 5);
        if (every is < 0 or > 10000) throw new InvalidOperationException("Social:GiftEveryWins must be within 0..10000.");
        if (every == 0) return after;
        long previous = before.Kills?.Values.Sum(n => (long)Math.Max(0, n)) ?? 0;
        long current = after.Kills?.Values.Sum(n => (long)Math.Max(0, n)) ?? 0;
        if (current <= previous || current / every <= previous / every || Occupied(after) >= Economy.BagSize(after)) return after;
        var items = after.Items.ToDictionary(e => e.Key, e => new Dictionary<int, int>(e.Value));
        if (!items.TryGetValue(SocialService.PackItems, out var packs)) items[SocialService.PackItems] = packs = new();
        packs[SocialService.PackId] = checked(packs.GetValueOrDefault(SocialService.PackId) + 1);
        pack = SocialService.PackId;
        return after with { Items = items };
    }
}
