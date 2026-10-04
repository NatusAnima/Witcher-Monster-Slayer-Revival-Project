namespace WitcherRevival.Server.Net;

/// <summary>Explicit reconstruction choices where original 1.1.116 server values were not recovered.
/// These defaults are authored balance, not historical measurements. A server restart and fresh client
/// catalogue load are required after changing them. Reject invalid values instead of silently clamping.</summary>
public sealed record SkillBalancePolicy(
    int ExtraPotionChancePercent = 10,
    int SquallElementalRemains = 1,
    int ResolveFloorPercentPerRank = 10,
    int AttackAdrenalineBonus = 1,
    int EventAdrenalineGain = 1,
    int InitialAdrenalineGain = 3,
    int FinalBlowSurvivalChancePercent = 10,
    int InstantSignRecoveryChancePercent = 10,
    int BombAngleReductionDegrees = 15,
    int WitcherAuraIntervalSeconds = 3600,
    int WitcherAuraLifetimeSeconds = 3600)
{
    public static SkillBalancePolicy Default { get; } = new();

    public static SkillBalancePolicy FromConfiguration(IConfiguration configuration)
    {
        int Value(string name, int fallback, int min, int max)
        {
            string key = "Reconstruction:" + name;
            string? text = configuration[key];
            if (text is null) return fallback;
            if (!int.TryParse(text, System.Globalization.NumberStyles.Integer,
                    System.Globalization.CultureInfo.InvariantCulture, out int value) || value < min || value > max)
                throw new InvalidOperationException($"{key} must be an integer from {min} to {max}.");
            return value;
        }
        var policy = new SkillBalancePolicy(
            Value(nameof(ExtraPotionChancePercent), 10, 0, 100),
            Value(nameof(SquallElementalRemains), 1, 1, 100),
            Value(nameof(ResolveFloorPercentPerRank), 10, 0, 30),
            Value(nameof(AttackAdrenalineBonus), 1, 0, 20),
            Value(nameof(EventAdrenalineGain), 1, 0, 10),
            Value(nameof(InitialAdrenalineGain), 3, 0, 10),
            Value(nameof(FinalBlowSurvivalChancePercent), 10, 0, 100),
            Value(nameof(InstantSignRecoveryChancePercent), 10, 0, 100),
            Value(nameof(BombAngleReductionDegrees), 15, 0, 20),
            // August 2021 player reports describe one hourly aura monster lasting one hour.
            // These configurable defaults are reconstruction policy, not recovered server data.
            Value(nameof(WitcherAuraIntervalSeconds), 3600, 300, 86400),
            Value(nameof(WitcherAuraLifetimeSeconds), 3600, 300, 86400));
        if (policy.WitcherAuraLifetimeSeconds > policy.WitcherAuraIntervalSeconds)
            throw new InvalidOperationException("Reconstruction:WitcherAuraLifetimeSeconds must not exceed WitcherAuraIntervalSeconds.");
        return policy;
    }

    // Roll once while starting a craft, in the same profile transaction as ingredient consumption.
    // The saved quantity survives skill/config changes, retries and process restarts.
    public int CraftOutputCount(LocalProfileStore.PlayerState player, Economy.Recipe recipe) =>
        recipe.ItemType == Economy.TypePotion && player.Skills.Contains(63) &&
        System.Security.Cryptography.RandomNumberGenerator.GetInt32(100) < ExtraPotionChancePercent ? 2 : 1;
}
