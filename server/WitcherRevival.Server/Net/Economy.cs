namespace WitcherRevival.Server.Net;

/// <summary>
/// Alchemy (ingredients, formulae, crafting stations) and Thorstein's shop for reconstructed profiles.
/// Sources: Client (1.1.116 Container schema and DataMember names, ItemTypeIds, I2 names, the alchemy and shop
/// sprite atlases, shop tabs and groups); Community (TheGamer "Every Available Potion/Oil/Bomb", 2021:
/// formulae, crafting times and shop prices per stack of 3; Gamepressure crafting guide: a basic station from
/// the start, a 20-use and a 100-use faster station). Everything else is Authored and says so.
/// </summary>
public static class Economy
{
    // Client ItemTypeIds.
    public const int TypeIngredient = 1, TypeBomb = 2, TypePotion = 3, TypeOil = 4, TypeLure = 5, TypeSensesPotion = 6,
        TypeArmor = 8, TypeSword = 9, TypeBag = 11, TypeBrewer = 12, TypeFriendPack = 15;

    public static string? KindOf(int itemType) => itemType switch
    {
        TypeIngredient => ItemKinds.Ingredients,
        TypeBomb => ItemKinds.Bombs,
        TypePotion => ItemKinds.Potions,
        TypeOil => ItemKinds.Oils,
        TypeLure => ItemKinds.Lures,
        TypeSensesPotion => ItemKinds.SensesPotions,
        TypeFriendPack => SocialService.PackItems,
        _ => null,
    };

    // ── Ingredients ─────────────────────────────────────────────────────────────────────────
    // Client: ITEMS/NAMES/INGREDIENTS/<SLUG> and icon_ingredient_<slug> (alchemy_atlas). Ids take the first
    // hundred (item ids share one client storage across kinds). Remains follow monster_families ids.
    public const int Herba = 101, Radix = 102, Tissue = 103;

    public static readonly IReadOnlyList<(int Id, string Slug, int? Family)> Ingredients = new (int, string, int?)[]
    {
        (Herba, "ingredient_herba", null), (Radix, "ingredient_radix", null),
        (Tissue, "ingredient_powdered_monster_tissue", null),
        (104, "ingredient_necrophage_remains", 1), (105, "ingredient_draconid_remains", 2),
        (106, "ingredient_ogroid_remains", 3), (107, "ingredient_hybrid_remains", 4),
        (108, "ingredient_elemental_remains", 5), (109, "ingredient_relict_remains", 6),
        (110, "ingredient_specter_remains", 7), (111, "ingredient_insectoid_remains", 8),
        (112, "ingredient_vampire_remains", 10), (113, "ingredient_cursed_remains", 11),
    };

    public static int? RemainsOfFamily(int family) => Ingredients.FirstOrDefault(i => i.Family == family).Id is var id && id != 0 ? id : null;

    /// <summary>Loot of a won fight, one item id per unit (CombatEnd Loot is a list of item ids the client adds
    /// to the inventory). Community: remains and powdered tissue come from slain monsters. Amounts Authored:
    /// two powdered tissue plus remains of the monster's family, one more of each above difficulty 1.</summary>
    public static List<int> FightLoot(int monsterId, int difficulty)
    {
        var loot = new List<int> { Tissue, Tissue };
        if (difficulty > 1) loot.Add(Tissue);
        // Families of the world bestiary (the client's bestiary texts); story actors leave no remains.
        if (WorldBestiary.FamilyOf(monsterId) is int family && RemainsOfFamily(family) is int remains)
        {
            loot.Add(remains);
            if (difficulty > 1) loot.Add(remains);
        }
        return loot;
    }

    // ── Senses potion ───────────────────────────────────────────────────────────────────────
    public const int Falcon = 601;

    // ── Crafting stations ───────────────────────────────────────────────────────────────────
    // Client: brewers table (id, slug, uses, time_coefficient), icon_brewer_<slug>; BrewerSlot shows no use
    // counter for a negative UsesLeft; time_coefficient is an int percentage of the formula's time
    // (AlchemyRecipeSlot.GetCraftingTimeText: crafting_time / 60 * coefficient / 100 minutes). Community: a basic
    // station from the start, a faster 20-use and 100-use station. Uses 0 marks the unlimited basic station;
    // half the time on the faster stations is Authored. The ids are the client's own (AlchemyBrewingPanel:
    // INFINITE_BREWER 1, SMALL_BREWER 2, BIG_BREWER 3): its "Add Station" list asks the table for ids 2 and 3 only.
    // Saves from before used 1201-1203 (PlayerService.EnsureBrewers moves them).
    public sealed record Brewer(int Id, string Slug, int Uses, int TimeCoefficient);

    public static readonly Brewer BasicBrewer = new(1, "brewer_basic", 0, 100);
    public static readonly IReadOnlyList<Brewer> Brewers = new[]
    {
        BasicBrewer, new Brewer(2, "brewer_small", 20, 50), new Brewer(3, "brewer_big", 100, 50),
    };

    public const long BasicBrewerInstance = 1;

    // ── Bags ────────────────────────────────────────────────────────────────────────────────
    // Client: ITEMS/NAMES/BUNDLES/BUNDLE_95..99 (Bag, Small pouch, Medium-sized pouch, Spacious pouch, Set of
    // saddlebags) with descriptions "Adds 50/50/100/200/400 inventory slots. One-time purchase."; a bag item adds
    // its amount to the inventory size (PlayerInventory.TryAddItem) and the client stops at 1000
    // (CanExpandInventory). Community (wiki, v1.1): 200 slots at the start, the five bags sold once each in the
    // Equipment tab for 500/500/1000/2000/4000 orens. The client has no bag group (GroupType), so they sit in Items.
    public static readonly IReadOnlyList<(int Bundle, int Slots, int Price)> Bags =
        new[] { (95, 50, 500), (96, 50, 500), (97, 100, 1000), (98, 200, 2000), (99, 400, 4000) };

    public const int MaxBagSize = 1000;

    /// <summary>How many items the player's inventory holds: the dashboard's starting size plus the bags bought.</summary>
    public static int BagSize(LocalProfileStore.PlayerState? player) => Math.Min(MaxBagSize,
        (int)WorldTuning.Current.Get(WorldTuning.StartingBag) +
        Bags.Where(bag => player?.OneTimeBundles?.Contains(bag.Bundle) == true).Sum(bag => bag.Slots));

    // ── Formulae ────────────────────────────────────────────────────────────────────────────
    // Community (TheGamer 2021): times and ingredients. Family oils take other families' remains as listed;
    // The pinned pre-1.2 Wiki potion and skill tables additionally describe skill-unlocked formulae.
    // Squall's elemental-remains quantity is absent there: one is an authored reconstruction value.
    // Recipe IDs are authored, stable identities; the snowball bomb has no recovered formula.
    public sealed record Recipe(int Id, int ItemType, int Output, string Slug, int Minutes,
        (int Ingredient, int Amount)[] Ingredients, int? RequiredSkill = null);

    private static (int, int)[] Need(int tissue, int herba, int radix = 0) =>
        new[] { (Tissue, tissue), (Herba, herba), (Radix, radix) }.Where(n => n.Item2 > 0).ToArray();

    private static (int, int)[] FamilyOil(int remains, int herba = 3) => new[] { (remains, 5), (Herba, herba), (Radix, 2) };

    public static readonly IReadOnlyList<Recipe> Recipes = new Recipe[]
    {
        new(2101, TypePotion, 201, "potion_thunderbolt", 10, Need(3, 2)),
        new(2102, TypePotion, 205, "potion_swallow", 30, Need(5, 3, 1)),
        new(2103, TypePotion, 202, "potion_swift", 30, Need(5, 3, 1)),
        new(2104, TypePotion, 203, "potion_blizzard", 30, Need(5, 3, 1)),
        new(2105, TypePotion, 204, "potion_tawnyowl", 30, Need(5, 3, 1), 50),
        new(2106, TypePotion, 206, "potion_cat", 30, Need(5, 3, 1), 52),
        new(2107, TypePotion, 207, "potion_squall", 30, new[] { (Tissue, 7), (Herba, 7), (108, 1) }, 56),
        new(2108, TypePotion, 208, "potion_wolverine", 30, Need(5, 3, 1), 61),
        new(2109, TypePotion, 209, "potion_mariborforest", 30, Need(5, 3, 1)),
        new(6101, TypeSensesPotion, Falcon, "senses_potion_falcon", 10, Need(3, 2)),
        new(3101, TypeOil, 301, "oil_basic", 20, Need(5, 3)),
        new(3102, TypeOil, 302, "oil_necrophage", 60, FamilyOil(113)),
        new(3103, TypeOil, 304, "oil_cursed", 60, FamilyOil(112)),
        new(3104, TypeOil, 303, "oil_ogroid", 60, FamilyOil(105)),
        new(3105, TypeOil, 305, "oil_relict", 60, FamilyOil(108)),
        new(3106, TypeOil, 306, "oil_hybrid", 60, FamilyOil(106)),
        new(3107, TypeOil, 307, "oil_insectoid", 60, FamilyOil(110)),
        new(3108, TypeOil, 308, "oil_draconid", 60, FamilyOil(104)),
        new(3109, TypeOil, 309, "oil_specter", 60, FamilyOil(109)),
        new(3110, TypeOil, 310, "oil_elemental", 60, FamilyOil(107)),
        new(3111, TypeOil, 311, "oil_vampire", 60, FamilyOil(111)),
        new(4101, TypeBomb, 401, "bomb_basic", 40, Need(5, 3, 1)),
        new(4102, TypeBomb, 402, "bomb_grapeshot", 120, Need(10, 7, 3)),
        new(4103, TypeBomb, 403, "bomb_moondust", 120, Need(10, 7, 3)),
        new(4104, TypeBomb, 404, "bomb_dancingstar", 120, Need(10, 7, 3)),
        new(4105, TypeBomb, 405, "bomb_dimeritium", 120, Need(10, 7, 3)),
    };

    public const int RecipeTier = 1;

    public static Recipe ApplyPolicy(Recipe recipe, SkillBalancePolicy policy) => recipe.Id == 2107
        ? recipe with { Ingredients = recipe.Ingredients.Select(ingredient => ingredient.Ingredient == 108
            ? (108, policy.SquallElementalRemains) : ingredient).ToArray() }
        : recipe;

    /// <summary>Shared catalogue, unlock and direct-crafting eligibility. Existing crafted items and work
    /// remain owned; this controls only knowledge responses and starting another craft.</summary>
    public static bool KnowsRecipe(LocalProfileStore.PlayerState player, Recipe recipe)
    {
        int baseSkill = recipe.ItemType switch
        {
            TypePotion or TypeSensesPotion => 47,
            TypeOil => 46,
            TypeBomb => 48,
            _ => 0,
        };
        return baseSkill != 0 && player.Skills.Contains(baseSkill) &&
            (recipe.RequiredSkill is null || player.Skills.Contains(recipe.RequiredSkill.Value));
    }

    // Client GrantAdditionalPotion (effect45) adds one for each of these distinct owned utility skills.
    public static int PotionCapacity(LocalProfileStore.PlayerState player) =>
        1 + (player.Skills.Contains(54) ? 1 : 0) + (player.Skills.Contains(58) ? 1 : 0);

    public static bool ValidPotionSelection(LocalProfileStore.PlayerState player, IReadOnlyList<int> potions) =>
        potions.Count <= PotionCapacity(player) && potions.Distinct().Count() == potions.Count &&
        potions.All(id => Reconstruction.KnownItem(ItemKinds.Potions, id));

    /// <summary>Crafting seconds on a station (at least one second).</summary>
    public static int CraftingSeconds(Recipe recipe, Brewer brewer) =>
        Math.Max(1, recipe.Minutes * 60 * brewer.TimeCoefficient / 100);

    // ── Shop ────────────────────────────────────────────────────────────────────────────────
    // Client: shop_bundles (gold_price, discount, daily_discount, one_time, layout_*), shop_bundle_items and
    // shop_bundles_layout_group_name_categories; ShopTab (Basic, Alchemy, Equipment) and GroupType names
    // (Potions, Oils, Bombs, Items, Packs, Daily ...) are parsed from the categories; a one-element bundle
    // shows its item's name and icon, a larger one ITEMS/NAMES/BUNDLES/BUNDLE_<id> and icon_bundle_<id>, so
    // multi-item bundles keep client bundle ids; GroupType also has Baits. Community (TheGamer): stacks of 3 cost Thunderbolt/Falcon 30,
    // other potions 60, basic oil 75, family oils 150, basic bomb 150, other bombs 300. Other prices, the
    // contents of packs and the discounts are Authored.
    public sealed record Bundle(int Id, int GoldPrice, string Tab, string Group, string Layout,
        (int Type, int Item, int Amount)[] Items, int Priority, bool OneTime = false, int DailyDiscount = 25,
        int? InAppPrice = null);

    // ── Oren packs ──────────────────────────────────────────────────────────────────────────
    // Client: the shop's GroupType has Gold (4) and ItemTypeIds.GOLD is 10. When the wallet cannot pay a bundle,
    // ShopPurchaseWindow.TryPurchase (0x181A1A0) opens GoldOfferWindow, which lists the shop items whose first
    // element is gold (OnInitialized 0x17D0404) and reads the last of them when none covers the deficit (LoadData
    // 0x17CFF58): with no gold item it throws and leaves the shop dimmed. The client names bundles 77-82 "#0 gold
    // coins" (ITEMS/NAMES/BUNDLES/BUNDLE_77..82: a handful, a pouch, a chest, a small barrel, a fat sack, piles):
    // the original oren packs. They are priced in real money (shop_bundles.inapp_price_id -> inapp_prices,
    // inapp_price_shops by StoreType name, parsed in DataManager.LoadShop 0x17C2078). A client whose application id
    // is not com.spokko.witchermonsterslayer binds FakeInAppPurchasingSystem (TransactionModuleInstaller.BindStore
    // 0x18A5A6C), whose purchase costs nothing and sends BuyShopInAppBundle (76) with a fake receipt; this server
    // grants the pack for it, once per transaction. Pack sizes are Authored and kept small, as the purchase is free;
    // the price rows and product ids are Authored too.
    public const int TypeGold = 10;

    public sealed record OrenPack(int Bundle, int PriceId, int Orens, int PriceCents, string ProductId);

    public static readonly IReadOnlyList<OrenPack> OrenPacks = new OrenPack[]
    {
        new(77, 1, 50, 99, "orens_handful"), new(78, 2, 100, 199, "orens_pouch"), new(79, 3, 250, 499, "orens_chest"),
        new(80, 4, 500, 999, "orens_barrel"), new(81, 5, 1000, 1999, "orens_sack"), new(82, 6, 2000, 3999, "orens_piles"),
    };

    public static OrenPack? OrenPackOf(int bundleId) => OrenPacks.FirstOrDefault(p => p.Bundle == bundleId);

    private static Bundle Single(int id, int price, string tab, string group, int type, int item, int amount, int priority) =>
        new(id, price, tab, group, "OneByOne", new[] { (type, item, amount) }, priority);

    public static readonly IReadOnlyList<Bundle> Bundles = BuildBundles();

    private static List<Bundle> BuildBundles()
    {
        var bundles = new List<Bundle>();
        int priority = 0;
        foreach (var (id, _) in Reconstruction.Potions)
            bundles.Add(Single(1000 + id, id == 201 ? 30 : 60, "Alchemy", "Potions", TypePotion, id, 3, priority++));
        bundles.Add(Single(1000 + Falcon, 30, "Alchemy", "Potions", TypeSensesPotion, Falcon, 3, priority++));
        foreach (var oil in Reconstruction.Oils)
            bundles.Add(Single(1000 + oil.Id, oil.FamilyOil ? 150 : 75, "Alchemy", "Oils", TypeOil, oil.Id, 3, priority++));
        foreach (int bomb in new[] { 401 }.Concat(Reconstruction.ExtraBombs.Select(b => b.Id)))
            bundles.Add(Single(1000 + bomb, bomb == 401 ? 150 : 300, "Alchemy", "Bombs", TypeBomb, bomb, 3, priority++));
        // Baits one at a time (Community, Digital Trends 2021: a bait costs 200 gold), only those whose class
        // a nemeton can hold (WorldNests).
        foreach (var lure in WorldNests.Lures.Where(l => l.Sold))
            bundles.Add(Single(1000 + lure.Id, WorldNests.BaitPrice, "Alchemy", "Baits", TypeLure, lure.Id, 1, priority++) with { DailyDiscount = 0 });
        // Ingredients and stations (Authored prices); remains come in fives.
        bundles.Add(Single(1000 + Tissue, 50, "Alchemy", "Items", TypeIngredient, Tissue, 10, priority++));
        foreach (var remains in Ingredients.Where(i => i.Family is not null))
            bundles.Add(Single(1000 + remains.Id, 60, "Alchemy", "Items", TypeIngredient, remains.Id, 5, priority++));
        bundles.Add(new Bundle(129, 80, "Alchemy", "Items", "TwoByOne",
            new[] { (TypeIngredient, Herba, 10), (TypeIngredient, Radix, 5) }, priority++));
        // bundle ids stay 2202/2203 (one-time purchases already recorded under them)
        bundles.Add(Single(2202, 300, "Alchemy", "Items", TypeBrewer, 2, 1, priority++) with { DailyDiscount = 0 });
        bundles.Add(Single(2203, 1000, "Alchemy", "Items", TypeBrewer, 3, 1, priority++) with { DailyDiscount = 0 });
        // Equipment, bought once (Community prices, see Reconstruction.Swords and Armors).
        foreach (var armor in Reconstruction.Armors.Where(a => a.Price is not null))
            bundles.Add(Single(3000 + armor.Id, armor.Price!.Value, "Equipment", "Armors", TypeArmor, armor.Id, 1, priority++)
                with { OneTime = true, DailyDiscount = 0 });
        foreach (var sword in Reconstruction.Swords.Where(s => s.Price is not null))
            bundles.Add(Single(4000 + sword.Id, sword.Price!.Value, "Equipment",
                sword.SwordType == Reconstruction.SteelSword ? "Steel_Swords" : "Silver_Swords", TypeSword, sword.Id, 1, priority++)
                with { OneTime = true, DailyDiscount = 0 });
        foreach (var bag in Bags)
            bundles.Add(Single(bag.Bundle, bag.Price, "Equipment", "Items", TypeBag, 1, bag.Slots, priority++)
                with { OneTime = true, DailyDiscount = 0 });
        foreach (var pack in OrenPacks)
            bundles.Add(new Bundle(pack.Bundle, 0, "Basic", "Gold", "OneByOne", new[] { (TypeGold, 1, pack.Orens) }, priority++,
                DailyDiscount: 0, InAppPrice: pack.PriceId));
        // Chests (client bundles 64 "A little something" and 65 "For professionals").
        bundles.Add(new Bundle(64, 250, "Basic", "Packs", "TwoByOne", new[]
        {
            (TypePotion, 205, 2), (TypePotion, 201, 2), (TypeOil, 301, 2), (TypeBomb, 401, 2),
        }, priority++, DailyDiscount: 0));
        bundles.Add(new Bundle(65, 900, "Basic", "Packs", "TwoByOne", new[]
        {
            (TypePotion, 205, 3), (TypePotion, 201, 3), (TypePotion, 203, 3), (TypeOil, 301, 3), (TypeBomb, 402, 3),
            (TypeIngredient, Tissue, 10), (TypeIngredient, Herba, 10), (TypeIngredient, Radix, 5),
        }, priority++, DailyDiscount: 0));
        return bundles;
    }

    public static Bundle? BundleById(int id) => Bundles.FirstOrDefault(b => b.Id == id);

    /// <summary>Today's daily deals (GetDailyShopBundles 79): three potion, oil or bomb stacks, the same for a
    /// UTC day (Authored rotation).</summary>
    public static List<int> DailyDeals(long unixSeconds)
    {
        var pool = Bundles.Where(b => b.Group is "Potions" or "Oils" or "Bombs").Select(b => b.Id).ToList();
        long day = unixSeconds / 86_400;
        var rng = new Random((int)(day % int.MaxValue));
        return pool.OrderBy(_ => rng.Next()).Take(3).OrderBy(id => id).ToList();
    }

    /// <summary>Gold price of a bundle now: the daily discount applies to today's daily deals.</summary>
    public static int PriceOf(Bundle bundle, long unixSeconds) =>
        DailyDeals(unixSeconds).Contains(bundle.Id)
            ? bundle.GoldPrice * (100 - bundle.DailyDiscount) / 100
            : bundle.GoldPrice;

    /// <summary>Unit prices of the combat preparation's recommended purchase (auto_equip_items_prices):
    /// a third of the shop stack price, rounded up.</summary>
    public static IEnumerable<(int Type, int Item, int Price)> UnitPrices() => Bundles
        .Where(b => b.Items.Length == 1 && b.Items[0].Type is TypePotion or TypeOil or TypeBomb)
        .Select(b => (b.Items[0].Type, b.Items[0].Item, (b.GoldPrice + b.Items[0].Amount - 1) / b.Items[0].Amount));

    // ── Static data rows ────────────────────────────────────────────────────────────────────
    private static string J(object value) => System.Text.Json.JsonSerializer.Serialize(value);

    public static void AddRows(Dictionary<string, string[]> rows, SkillBalancePolicy? policy = null)
    {
        rows["ingredients"] = Ingredients.Select(i => J(new Dictionary<string, object>
            { ["id"] = i.Id, ["slug"] = i.Slug, ["priority"] = i.Id })).ToArray();
        rows["senses_potions"] = new[] { J(new Dictionary<string, object>
            { ["id"] = Falcon, ["slug"] = "senses_potion_falcon", ["priority"] = 0 }) };
        rows["brewers"] = Brewers.Select(b => J(new Dictionary<string, object>
            { ["id"] = b.Id, ["slug"] = b.Slug, ["uses"] = b.Uses, ["time_coefficient"] = b.TimeCoefficient })).ToArray();
        rows["recipe_tiers"] = new[] { J(new Dictionary<string, object> { ["id"] = RecipeTier, ["name"] = "", ["sprite"] = "" }) };
        foreach (var (type, table) in new[] { (TypePotion, "potion"), (TypeOil, "oil"), (TypeBomb, "bomb"), (TypeSensesPotion, "senses_potion") })
        {
            var recipes = Recipes.Where(r => r.ItemType == type).Select(r => ApplyPolicy(r, policy ?? SkillBalancePolicy.Default)).ToList();
            rows[$"{table}_recipes"] = recipes.Select(r => J(new Dictionary<string, object>
            {
                ["id"] = r.Id, ["slug"] = r.Slug, ["output"] = r.Output, ["tier_id"] = RecipeTier,
                ["crafting_time"] = r.Minutes * 60, ["priority"] = r.Id,
            })).ToArray();
            rows[$"{table}_recipe_ingredients"] = recipes.SelectMany(r => r.Ingredients.Select(n => J(new Dictionary<string, object>
                { ["recipe_id"] = r.Id, ["ingredient_id"] = n.Ingredient, ["amount"] = n.Amount }))).ToArray();
        }
        rows["shop_bundles"] = Bundles.Select(b => J(new Dictionary<string, object?>
        {
            ["id"] = b.Id, ["gold_price"] = b.GoldPrice, ["discount"] = 0, ["daily_discount"] = b.DailyDiscount,
            ["permanent"] = 1, ["layout_priority"] = b.Priority, ["one_time"] = b.OneTime ? 1 : 0, ["dev"] = 0,
            ["inapp_price_id"] = b.InAppPrice, ["name"] = "", ["icon"] = "", ["description"] = "",
            ["layout_type"] = b.Layout, ["layout_underlay"] = "None",
        })).ToArray();
        rows["inapp_prices"] = OrenPacks.Select(pack => J(new Dictionary<string, object>
            { ["id"] = pack.PriceId, ["amount"] = pack.PriceCents, ["name"] = pack.ProductId, ["product_type"] = "Consumable" })).ToArray();
        rows["inapp_price_shops"] = OrenPacks.SelectMany(pack => new[] { "GooglePlay", "AppStore" }.Select(store => J(new Dictionary<string, object>
            { ["inapp_price_id"] = pack.PriceId, ["name"] = pack.ProductId, ["shop_name"] = store, ["shop_price_id"] = pack.ProductId }))).ToArray();
        rows["shop_bundle_items"] = Bundles.SelectMany(b => b.Items.Select(item => J(new Dictionary<string, object>
            { ["shop_bundle_id"] = b.Id, ["item_type_id"] = item.Type, ["item_id"] = item.Item, ["amount"] = item.Amount }))).ToArray();
        rows["shop_bundles_layout_group_name_categories"] = Bundles.Select(b => J(new Dictionary<string, object>
            { ["shop_bundle_id"] = b.Id, ["layout_group_name_main_category"] = b.Tab, ["layout_group_name_sub_category"] = b.Group })).ToArray();
        rows["auto_equip_items_prices"] = UnitPrices().Select((p, n) => J(new Dictionary<string, object>
            { ["id"] = n + 1, ["item_type_id"] = p.Type, ["item_id"] = p.Item, ["gold_price"] = p.Price })).ToArray();
    }
}
