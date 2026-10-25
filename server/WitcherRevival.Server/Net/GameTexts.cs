using System.Globalization;

namespace WitcherRevival.Server.Net;

/// <summary>
/// The server's own texts in the game, in its nine languages (I2Languages order: English, Polish, German, Spanish, Italian,
/// French, Russian, Brazilian Portuguese, Japanese), worded like the game's own terms: its family names
/// (MONSTERS/FAMILIES/*), "gold coins" (UI/PANELS/SHOP/GOLD_COINS), "crafting station" (ITEMS/NAMES/BREWERS/*), the Spanish
/// "santuario" for a nemeton, the trinkets' names (ACHIEVEMENTS/NAMES/*). hook.js shows the player's language (its
/// CurrentLanguageCode before any "-"), else English.
/// </summary>
public static class GameTexts
{
    public static readonly string[] Languages = ["en", "pl", "de", "es", "it", "fr", "ru", "pt", "ja"];

    /// <summary>A text by language, given in <see cref="Languages"/>' order.</summary>
    public static Dictionary<string, string> Of(params string[] texts)
    {
        if (texts.Length != Languages.Length) throw new ArgumentException("one text per language");
        return Languages.Zip(texts).ToDictionary(p => p.First, p => p.Second);
    }

    /// <summary>[template] in every language with its {0}, {1}… filled; an argument that is itself by language fills its own.</summary>
    public static Dictionary<string, string> Format(Dictionary<string, string> template, params object[] args) =>
        template.ToDictionary(p => p.Key, p => string.Format(CultureInfo.InvariantCulture, p.Value,
            args.Select(a => a is Dictionary<string, string> byLanguage ? byLanguage[p.Key] : a).ToArray()));

    // ── Trinket bonuses (TrinketBuffs) ───────────────────────────────────────────────────────────

    public static readonly Dictionary<string, string> Bonus =
        Of("Bonus: ", "Premia: ", "Bonus: ", "Bonificación: ", "Bonus: ", "Bonus : ", "Бонус: ", "Bônus: ", "ボーナス：");

    public static readonly Dictionary<string, string> Herbs = Of("+{0}% herbs", "+{0}% ziół", "+{0} % Kräuter",
        "+{0} % de hierbas", "+{0}% di erbe", "+{0} % d'herbes", "+{0}% трав", "+{0}% de ervas", "薬草+{0}%");

    public static readonly Dictionary<string, string> NestGold = Of("+{0}% gold coins from nemeta",
        "+{0}% złotych monet z nemetonów", "+{0} % Goldmünzen aus Nemeta", "+{0} % de monedas de oro de los santuarios",
        "+{0}% di monete d'oro dai nemeton", "+{0} % de pièces d'or des nemetons", "+{0}% золотых монет за неметоны",
        "+{0}% de moedas de ouro dos nemetons", "ネメトンのゴールドコイン+{0}%");

    public static readonly Dictionary<string, string> FightExp = Of("+{0}% experience from fights", "+{0}% doświadczenia z walk",
        "+{0} % Erfahrung aus Kämpfen", "+{0} % de experiencia en combate", "+{0}% di esperienza dai combattimenti",
        "+{0} % d'expérience en combat", "+{0}% опыта за бои", "+{0}% de experiência em combate", "戦闘の経験値+{0}%");

    /// <summary>{0} the percentage, {1} the family (<see cref="Against"/>).</summary>
    public static readonly Dictionary<string, string> FamilyExp = Of("+{0}% experience and +{0}% attack against {1}",
        "+{0}% doświadczenia i +{0}% do ataku przeciw {1}", "+{0} % Erfahrung und +{0} % Angriff gegen {1}",
        "+{0} % de experiencia y +{0} % de ataque contra {1}", "+{0}% di esperienza e +{0}% di attacco contro {1}",
        "+{0} % d'expérience et +{0} % d'attaque contre {1}", "+{0}% опыта и +{0}% к атаке против {1}",
        "+{0}% de experiência e +{0}% de ataque contra {1}", "経験値+{0}%、{1}への攻撃+{0}%");

    /// <summary>The effects panel's name of a trinket's attack bonus: {0} the percentage, {1} the family, {2} the trinket.</summary>
    public static readonly Dictionary<string, string> AttackName = Of("{2}: +{0}% attack against {1}",
        "{2}: +{0}% do ataku przeciw {1}", "{2}: +{0} % Angriff gegen {1}", "{2}: +{0} % de ataque contra {1}",
        "{2}: +{0}% di attacco contro {1}", "{2} : +{0} % d'attaque contre {1}", "{2}: +{0}% к атаке против {1}",
        "{2}: +{0}% de ataque contra {1}", "{2}：{1}への攻撃+{0}%");

    public static readonly Dictionary<string, string> Ingredients = Of("+{0}% ingredients from fights",
        "+{0}% składników z walk", "+{0} % Zutaten aus Kämpfen", "+{0} % de ingredientes en combate",
        "+{0}% di ingredienti dai combattimenti", "+{0} % d'ingrédients en combat", "+{0}% ингредиентов за бои",
        "+{0}% de ingredientes em combate", "戦闘で得る材料+{0}%");

    public static readonly Dictionary<string, string> Slots = Of("+{0} inventory slots", "+{0} miejsc w ekwipunku",
        "+{0} Inventarplätze", "+{0} huecos en el inventario", "+{0} spazi nell'inventario", "+{0} emplacements d'inventaire",
        "+{0} мест в рюкзаке", "+{0} espaços no inventário", "所持品の枠+{0}");

    public static readonly Dictionary<string, string> Station = Of("a second crafting station that never wears out",
        "drugie stanowisko alchemiczne, które nigdy się nie zużywa", "eine zweite Werkbank, die sich nie abnutzt",
        "una segunda mesa de fabricación que nunca se gasta", "un secondo laboratorio portatile che non si esaurisce mai",
        "un deuxième atelier de fabrication qui ne s'use jamais", "второй набор для алхимии, который никогда не изнашивается",
        "uma segunda estação de criação que nunca se desgasta", "消耗しない2台目の製作器");

    /// <summary>A family after "against" (each language's case: Polish dative, Russian genitive, an Italian and French article).
    /// Families: 1 necrophage, 2 draconid, 6 relict, 7 specter, 11 cursed (monster_families).</summary>
    public static readonly IReadOnlyDictionary<int, Dictionary<string, string>> Against = new Dictionary<int, Dictionary<string, string>>
    {
        [1] = Of("necrophages", "trupojadom", "Nekrophagen", "necrófagos", "i necrofagi", "les nécrophages", "трупоедов",
            "necrófagos", "屍鬼"),
        [2] = Of("draconids", "drakonidom", "Drakoniden", "dracónidos", "i dragonidi", "les draconides", "драконидов",
            "draconídeos", "飛龍種"),
        [6] = Of("relicts", "reliktom", "Relikte", "relictos", "le creature ancestrali", "les vestiges", "реликтов", "relictos",
            "遺存種"),
        [7] = Of("specters", "upiorom", "Geister", "espectros", "gli spettri", "les spectres", "духов и призраков", "espectros",
            "悪霊"),
        [11] = Of("cursed ones", "istotom przeklętym", "Verfluchte", "malditos", "le creature maledette", "les créatures maudites",
            "проклятых", "amaldiçoados", "呪縛生物"),
    };

    /// <summary>The trinkets with an attack bonus, by slug: the game's names (ACHIEVEMENTS/NAMES/&lt;SLUG&gt;).</summary>
    public static readonly IReadOnlyDictionary<string, Dictionary<string, string>> TrinketNames = new Dictionary<string, Dictionary<string, string>>
    {
        ["trophy_lizard_slayer"] = Of("Lizard Slayer", "Pogromca jaszczurów", "Echsenschlächter", "Cazalagartos", "Ammazzarettili",
            "Cauchemar des lézards", "Убийца ящеров", "Exterminador de Lagartos", "リザードスレイヤー"),
        ["trophy_broken_sword"] = Of("The Striga's Demise", "Na pohybel strzydze", "Niedergang einer Striege", "La caída de la estrige",
            "La caduta della strige", "La disparition de la strige", "Смерть стрыги", "A morte da estrige", "ストリガの最期"),
        ["trophy_disturbed_the_water"] = Of("Disturbed the Water", "Mąciwoda", "Das Wasser aufgewühlt", "Aguas molestas",
            "Acque mosse", "En eaux troubles", "Круги на воде", "Perturbando Águas Calmas", "水中の格闘"),
        ["trophy_fear_no_more"] = Of("Fear no More", "Porzuć strach", "Fürchte nicht mehr", "Sin miedo", "Nessun timore",
            "Tranquillité d'esprit", "Страха нет", "Não Tenha Medo", "恐怖の克服"),
        ["trophy_child_drawing"] = Of("Cursebreaker", "Klątwołamacz", "Fluchbrecher", "Rompemaldiciones", "Spezza-maledizioni",
            "La malédiction brisée", "Экзорцизм", "Quebrando maldições", "呪いを破るもの"),
        ["trophy_mushroom_leshen"] = Of("Mushroom Sentinel", "Strażnik grzybni", "Pilzwächter", "Seta centinela", "Sentinella fungina",
            "Sentinelle des champignons", "Грибной страж", "Sentinela dos Cogumelos", "キノコの護り手"),
    };

    // ── Weather charms (Consumables; they reuse unused consumables' icons and replace those items' texts) ──────────────

    public static readonly IReadOnlyDictionary<int, (Dictionary<string, string> Name, Dictionary<string, string> Description)> Charms =
        new Dictionary<int, (Dictionary<string, string>, Dictionary<string, string>)>
        {
            [Consumables.Rain] = (
                Of("Rain Charm", "Amulet deszczu", "Regenamulett", "Amuleto de lluvia", "Amuleto della pioggia", "Charme de pluie",
                    "Амулет дождя", "Amuleto da Chuva", "雨のお守り"),
                Of("Brings rain where you are for an hour. Monsters that like rain come out and even leave the water, and the Squall " +
                    "potion works. Monsters already out stay until they leave.",
                    "Sprowadza deszcz tam, gdzie jesteś, na godzinę. Potwory, które lubią deszcz, wychodzą, a nawet opuszczają wodę, " +
                    "a eliksir Szkwał działa. Potwory, które już są na mapie, zostają, dopóki nie odejdą.",
                    "Lässt dort, wo du bist, eine Stunde lang Regen fallen. Monster, die Regen mögen, kommen hervor und verlassen sogar " +
                    "das Wasser, und der Trank Böe wirkt. Monster, die schon unterwegs sind, bleiben, bis sie gehen.",
                    "Hace llover donde estás durante una hora. Los monstruos a los que les gusta la lluvia salen e incluso abandonan " +
                    "el agua, y la poción Borrasca funciona. Los monstruos que ya están fuera se quedan hasta que se marchan.",
                    "Porta la pioggia dove ti trovi per un'ora. I mostri che amano la pioggia escono e lasciano persino l'acqua, e la " +
                    "pozione Nembo funziona. I mostri già in giro restano finché non se ne vanno.",
                    "Fait tomber la pluie là où vous êtes pendant une heure. Les monstres qui aiment la pluie sortent et quittent même " +
                    "l'eau, et la potion Grain fonctionne. Les monstres déjà présents restent jusqu'à leur départ.",
                    "На час вызывает дождь там, где вы находитесь. Чудовища, которые любят дождь, выходят и даже покидают воду, а " +
                    "эликсир «Шквал» действует. Чудовища, которые уже появились, остаются, пока не уйдут.",
                    "Traz chuva onde você está por uma hora. Monstros que gostam de chuva aparecem e até saem da água, e a poção " +
                    "Rajada funciona. Monstros que já estão por aí ficam até irem embora.",
                    "1時間、現在地に雨を降らせる。雨を好む怪物が現れ、水辺を離れることもある。驟雨の霊薬も効果を発揮する。すでに出現している" +
                    "怪物は去るまで留まる。")),
            [Consumables.Fog] = (
                Of("Fog Charm", "Amulet mgły", "Nebelamulett", "Amuleto de niebla", "Amuleto della nebbia", "Charme de brume",
                    "Амулет тумана", "Amuleto da Névoa", "霧のお守り"),
                Of("Brings fog where you are for an hour, and the monsters that like it come out. Monsters already out stay until " +
                    "they leave.",
                    "Sprowadza mgłę tam, gdzie jesteś, na godzinę, a potwory, które ją lubią, wychodzą. Potwory, które już są na mapie, " +
                    "zostają, dopóki nie odejdą.",
                    "Lässt dort, wo du bist, eine Stunde lang Nebel aufziehen, und Monster, die ihn mögen, kommen hervor. Monster, die " +
                    "schon unterwegs sind, bleiben, bis sie gehen.",
                    "Trae niebla donde estás durante una hora y salen los monstruos a los que les gusta. Los monstruos que ya están " +
                    "fuera se quedan hasta que se marchan.",
                    "Porta la nebbia dove ti trovi per un'ora, e i mostri che la amano escono. I mostri già in giro restano finché non " +
                    "se ne vanno.",
                    "Fait venir la brume là où vous êtes pendant une heure, et les monstres qui l'aiment sortent. Les monstres déjà " +
                    "présents restent jusqu'à leur départ.",
                    "На час вызывает туман там, где вы находитесь, и выходят чудовища, которые его любят. Чудовища, которые уже " +
                    "появились, остаются, пока не уйдут.",
                    "Traz névoa onde você está por uma hora, e os monstros que gostam dela aparecem. Monstros que já estão por aí " +
                    "ficam até irem embora.",
                    "1時間、現在地に霧を発生させ、霧を好む怪物が現れる。すでに出現している怪物は去るまで留まる。")),
            [Consumables.Clear] = (
                Of("Sun Charm", "Amulet słońca", "Sonnenamulett", "Amuleto de sol", "Amuleto del sole", "Charme de soleil",
                    "Амулет солнца", "Amuleto do Sol", "晴れのお守り"),
                Of("Clears the sky where you are for an hour. Monsters already out stay until they leave.",
                    "Rozpogadza niebo tam, gdzie jesteś, na godzinę. Potwory, które już są na mapie, zostają, dopóki nie odejdą.",
                    "Klärt eine Stunde lang den Himmel dort, wo du bist. Monster, die schon unterwegs sind, bleiben, bis sie gehen.",
                    "Despeja el cielo donde estás durante una hora. Los monstruos que ya están fuera se quedan hasta que se marchan.",
                    "Rasserena il cielo dove ti trovi per un'ora. I mostri già in giro restano finché non se ne vanno.",
                    "Dégage le ciel là où vous êtes pendant une heure. Les monstres déjà présents restent jusqu'à leur départ.",
                    "На час проясняет небо там, где вы находитесь. Чудовища, которые уже появились, остаются, пока не уйдут.",
                    "Limpa o céu onde você está por uma hora. Monstros que já estão por aí ficam até irem embora.",
                    "1時間、現在地の空を晴れにする。すでに出現している怪物は去るまで留まる。")),
        };

    // ── Packs opened from the inventory (Tuning inventory.openPacks) ──────────────────────────────────────────────────

    /// <summary>The pack's buttons (its info window, its count window), as the game's "[Open]." investigation answer words it.</summary>
    public static readonly Dictionary<string, string> Open =
        Of("Open", "Otwórz", "Öffnen", "Abrir", "Apri", "Ouvrir", "Открыть", "Abrir", "開ける");

    /// <summary>The count window's question for a pack, worded like UI/PANELS/ALCHEMY/MANAGEMENT_REMOVE_HEADER (#0: the item).</summary>
    public static readonly Dictionary<string, string> OpenHeader = Of("Do you want to open this item: #0?",
        "Czy chcesz otworzyć ten przedmiot: #0?", "Möchtest du diesen Gegenstand öffnen: #0?", "¿Quieres abrir este objeto: #0?",
        "Vuoi aprire questo oggetto: #0?", "Voulez-vous ouvrir cet <nobr>objet :</nobr> <nobr>#0 ?</nobr>", "Открыть предмет: #0?",
        "Você deseja abrir este item: #0?", "#0を開けますか？");

    /// <summary>The line added to the herbalist's pack's description ("random quantities of herbs or roots") while the
    /// preset's pack table holds more than herbs and roots.</summary>
    public static readonly Dictionary<string, string> RarerFinds = Of("Now and then it also holds rarer finds.",
        "Czasem zawiera też rzadsze znaleziska.", "Ab und zu enthält es auch seltenere Funde.",
        "De vez en cuando también contiene hallazgos más raros.", "Di tanto in tanto contiene anche reperti più rari.",
        "Il contient parfois aussi des trouvailles plus rares.", "Иногда в ней бывают и более редкие находки.",
        "De vez em quando, também traz achados mais raros.", "まれに、より珍しい品が入っていることもある。");

    // ── Oils (Tuning combat.oilsMultiply off: the original sum) ──────────────────────────────────

    public static readonly Dictionary<string, string> OilBaseDamage = Of(
        "Its bonus is a share of the sword's base damage: weaknesses, potions and skills add to it rather than multiply it.",
        "Premia to część podstawowych obrażeń miecza: słabości, eliksiry i umiejętności dodają się do niej, a nie ją mnożą.",
        "Der Bonus ist ein Anteil am Grundschaden des Schwerts: Schwächen, Tränke und Fähigkeiten addieren sich dazu, statt ihn zu vervielfachen.",
        "La bonificación es una parte del daño base de la espada: las debilidades, pociones y habilidades se suman a ella, no la multiplican.",
        "Il bonus è una parte del danno base della spada: debolezze, pozioni e abilità si sommano a esso, non lo moltiplicano.",
        "Le bonus est une part des dégâts de base de l'épée : faiblesses, potions et compétences s'y ajoutent au lieu de le multiplier.",
        "Бонус — это доля базового урона меча: уязвимости, эликсиры и навыки складываются с ним, а не умножают его.",
        "O bônus é uma parte do dano base da espada: fraquezas, poções e habilidades somam-se a ele, em vez de multiplicá-lo.",
        "このボーナスは剣の基本ダメージに対する割合です。弱点、ポーション、スキルの効果は掛け合わされず、足し合わされます。");
}
