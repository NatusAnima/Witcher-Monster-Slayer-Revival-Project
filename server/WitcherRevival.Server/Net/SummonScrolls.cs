namespace WitcherRevival.Server.Net;

/// <summary>
/// The summoning scrolls (item type 16). The 1.1.116 client ships a name, a description and an icon for each of these slugs
/// (ITEMS/NAMES/SUMMONING_SCROLLS/&lt;SLUG&gt;, icon_&lt;slug&gt;); each group follows its own description, e.g. "Summons 5 random
/// draconids", "Summons one rare or legendary elemental", "Summons 3 random common monsters". Id 1 stays the tutorial's free
/// scroll and id 2 the basic scroll the weekly hunt pays.
/// </summary>
public static class SummonScrolls
{
    public const int ItemType = 16, Basic = 2, Lesser = 3, Legendary = 4, OgroidFive = 7;

    /// <summary>A scroll's group: so many commons, so many "common or rare", so many "rare or legendary" and so many
    /// legendaries, of one family (null: any). Price in orens when the shop sells it (Tuning shop.scrolls).</summary>
    public sealed record Scroll(int Id, string Slug, int Common, int CommonOrRare, int RareOrLegendary, int LegendaryOnly,
        int? Family, int Price);

    // Families: PreloaderStaticData monster_families (1 necrophage, 2 draconid, 3 ogroid, 4 hybrid, 5 elemental, 6 relict,
    // 7 specter, 8 insectoid, 10 vampire, 11 cursed).
    private static Scroll Five(int id, string slug, int family) => new(id, slug, 4, 1, 0, 0, family, 500);

    public static readonly IReadOnlyList<Scroll> All = new Scroll[]
    {
        new(Basic, "summoning_scroll_basic", 4, 1, 0, 0, null, 300),        // 4 common and 1 common or rare
        new(Lesser, "summoning_scroll_lesser", 3, 0, 0, 0, null, 150),      // 3 random common monsters
        new(Legendary, "summoning_scroll_legendary", 0, 0, 0, 1, null, 1500),
        Five(5, "summoning_scroll_necrophage", 1), Five(6, "summoning_scroll_draconid", 2),
        Five(OgroidFive, "summoning_scroll_ogroid_new", 3), Five(8, "summoning_scroll_specter", 7),
        Five(9, "summoning_scroll_cursed", 11), Five(10, "summoning_scroll_elementa_new", 5),
        Five(11, "summoning_scroll_hybrid", 4), Five(12, "summoning_scroll_insectoid", 8),
        Five(13, "summoning_scroll_relict", 6), Five(14, "summoning_scroll_vampire", 10),
        new(15, "summoning_scroll_elementa", 0, 0, 1, 0, 5, 800),            // one rare or legendary elemental
        new(16, "summoning_scroll_ogroids", 0, 0, 1, 0, 3, 800),             // one rare or legendary ogroid
        new(17, "summoning_scroll_specters", 2, 1, 0, 0, 7, 400),            // 3 random specters
    };

    public static Scroll? ById(int id) => All.FirstOrDefault(s => s.Id == id);
}
