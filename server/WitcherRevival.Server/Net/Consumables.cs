namespace WitcherRevival.Server.Net;

/// <summary>
/// Consumables (item type 7): used from the inventory (UseConsumable 99), each starts a timed player modifier. The client
/// names them ITEMS/NAMES/CONSUMABLES/&lt;SLUG&gt;, describes them with the modifier's effect power (#0) and the duration (#1),
/// and draws icon_&lt;slug&gt;. The Experience and Ingredients Scrolls are the client's own (xp_booster, gathering_booster); the
/// weather items reuse unused consumable slugs for their icons, and hook.js gives them their names (Revival only).
/// </summary>
public static class Consumables
{
    public const int ItemType = 7;
    public const int ExperienceScroll = 1, IngredientsScroll = 2, Rain = 3, Fog = 4, Clear = 5;

    /// <summary>[Weather]: the GetWeatherResponse code the item forces (3 rain, 5 fog, 6 clear), else null. [Effect] and
    /// [Power] feed the description's #0 (an empty effect list is accepted); [Price] in orens when the shop sells it.</summary>
    public sealed record Consumable(int Id, string Slug, int Modifier, string ModifierSlug, int? Effect, int Power, int Duration,
        int? Weather, int? Price);

    public static readonly IReadOnlyList<Consumable> All = new Consumable[]
    {
        // Wiki (The Witcher Monster Slayer scrolls): "increases experience gain by 100% … lasts for 30 minutes".
        new(ExperienceScroll, "xp_booster", 911, "consumable_exp_booster", 65, 100, 1800, null, null),
        // The client's text: "increases the number of alchemy ingredients acquired from monsters and plants by #0%".
        new(IngredientsScroll, "gathering_booster", 912, "consumable_gathering_booster", 71, 50, 1800, null, null),
        new(Rain, "interaction_booster", 913, "consumable_weather_rain", null, 0, 3600, 3, 250),
        new(Fog, "consumable_perfume", 914, "consumable_weather_fog", null, 0, 3600, 5, 250),
        new(Clear, "consumable_ringshaped_cracknel", 915, "consumable_weather_clear", null, 0, 3600, 6, 250),
    };

    public static Consumable? ById(int id) => All.FirstOrDefault(c => c.Id == id);
}
