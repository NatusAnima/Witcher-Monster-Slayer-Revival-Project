# Feature ideas

The maintainer's idea list (2026-10-25), ordered from the easiest to the hardest. These are ideas, not commitments. The sizes
are rough guesses made before reading the code each idea touches; recheck one before planning it.

**What each idea touches:**
- **[S]** server and map data only
- **[T]** new texts, icons or recolors in the game files
- **[H]** the hook changes client code (like the oils)
- **[A]** new 3D art, animation or UI screens

**Sizes:** XS a day or two · S a few days · M one to two weeks · L three to six weeks · XL one to three months · XXL more,
per idea.

## Groundwork that several ideas share

Doing one of these makes every idea that needs it cheaper. Each idea below names the ones it needs.

| Groundwork | What it is | Ideas that need it |
| --- | --- | --- |
| **Community server** | One shared world for every player, run by the maintainer | Shared lures, world hunts, school claims, tavern check-ins, weekly trial, alchemy discovery |
| **Landmarks in the map index** | The index keeps roads, rivers, water, parks, woods and beaches only. It needs bridges, cemeteries, places of worship, ruins and castles, mills, wells, peaks, springs, megaliths, pubs and squares; crossroads come from road junctions. Players rebuild their map once. | Landmark lairs, lairs, places of power, taverns, travelling merchant, treasure maps, world hunts |
| **Event calendar** | Dates, moon phases and seasons that change spawns, recipes and rewards | Real moon, real seasons, festivals, weekly trial, world hunts |
| **Generated quests** | Quests built by the server from templates and map names | Contracts, treasure maps, caravan escort, master craftsmen |
| **Game file pipeline** | Editing the game's Unity files and shipping them to players | Recolored variants, school gear sets and dyes, new monsters, season 2, new icons |
| **Combat hook** | The oils' damage hook, extended to monster stats, signs and gear | Elite monsters, school gear sets, runestones, places of power, world hunts, weekly trial |

## Tier 1: small (server only, existing systems)

**1. The real moon [S]** · XS · needs the event calendar
The full moon brings werewolves, and a new moon brings wraiths. The phase is computed on the phone, with no internet needed.

**2. Real seasons [S]** · XS · needs the event calendar
Winter brings ice elementals and ice trolls, summer brings noonwraiths, autumn brings ghouls and the dead.
Note: the season flips south of the equator (the player's latitude says which).

**3. Rural bonus [S]** · S
The countryside has fewer map features, so spawns there scale up.

**4. White Honey [S]** · S
Clears potion effects and toxicity.
Note: a consumable that ends the active modifiers (UseConsumable 99 already handles consumables). It clears toxicity once
Toxicity exists. Its name goes through the server's texts; its icon is borrowed until the game file pipeline exists.

**5. Cat potion [S, T]** · S
Shows night monsters during the day.
Note: listed as [H], but the server decides the spawns, and Falcon is already a senses potion (`TypeSensesPotion`), so Cat
can be a second senses potion that lets night monsters spawn by day. No client change.

**6. Roach [S, T]** · S
A companion who fills saddlebags as you walk, opened after 5 km, like Pokémon GO's eggs.
Note: the distance comes from the location updates the server already gets; the progress can show in the saddlebags' item
description. A Roach you can see is [A] and not part of this.

**7. Mutagens, school dyes and trinkets for families that don't have one yet** · S
Mutagens are a new ingredient type in the drop tables; the trinket system exists. The dyes belong with the school gear
sets (tier 3).

## Tier 2: medium (new server systems, texts, map landmarks)

**8. Landmark lairs [S]** · M · needs landmarks in the map index
An addition to the existing place mix:
- bridges get trolls
- cemeteries get ghouls, grave hags and wights at night
- churches and chapels get wraiths
- ruins and castles get nemeta and lairs
- crossroads at midnight get nightwraiths
- mills and wells get drowners and water hags
- mountain peaks get griffins and wyverns

**9. Festivals on the real calendar [S, T]** · M for the calendar, then S per festival · builds the event calendar
Saovine (Oct 31) brings wraiths and the dead. Belleteyn (May 1) brings sylvans and spriggans. Midinvaerne (Dec 21) brings
ice giants and barghests. Each gets limited monsters, recipes and a trinket.

**10. Decoctions [S, T]** · M
Hour-long buffs brewed from monster mutagens. The timed-effect system already exists.
Note: effects the client already knows stay [S, T]; a new kind of effect (such as damage against a family) goes through
the combat hook [H].

**11. Titles for feats [S, T]** · M
"Griffin's Bane" for 50 griffins, "Night Walker" for 100 kills after midnight, and so on.
Note: the kill counts exist. Where the game shows a title is not checked yet (the settings' account section has one, and
we hide it), so this may need [H].

**12. Shared lures [S]** · S on top of the community server
A bait placed on the map works for every player nearby.

**13. Potion tiers [S, T]** · M
Swallow, then Enhanced Swallow, then Superior, each needing rarer ingredients. Could tie into the alchemy rework.

**14. Places of Power [S, H]** · M · needs landmarks in the map index and the combat hook
Springs, stone circles, megaliths and ancient trees from the map. Touching one makes your signs stronger for an hour.

**15. Treasure maps [S, T]** · M · needs landmarks in the map index
A looted map carries a sketch or riddle about a real place ("where the river meets the old mill"). Find the spot and dig up
a chest.
Note: the riddle comes from map names; our tile renderer can draw the sketch.

**16. Travelling merchant [S, T]** · M · needs landmarks in the map index
Appears on a real town square for one day with rare stock.
Note: not checked yet whether a map spot can open a shop; Thorstein's shop graphs may allow it, or this needs [H].

**17. Rare pale variants [S, T]** · M
Any monster, about 1 in 500, white-tinted, with its own bestiary entry. That's the collecting hook.
Note: recoloring about 130 monsters in the game files is a lot of [T]; one tint applied at runtime by the hook [H] covers
them all.

## Tier 3: large (new frameworks or combat hooks)

**18. Taverns [S, T]** · M to L · needs landmarks in the map index and the community server
Real pubs and cafés become taverns. Rumours there hint at rare spawns nearby, and players who check in can see each other.

**19. Contracts [S, T, H]** · L · builds generated quests
A notice board in town names a real street or park: "a drowner haunts the canal by Ogrodowa Street" (any rarity). Two or
three clue spots follow: footprints, a body, a nest. Then the fight, then you haggle over the fee. Templates per monster
family, with places and names taken from the map, give endless local contracts. The game's quest windows and map markers
already exist.
Note: the conversation and the haggling live in the game's quest graphs, so this needs one generic contract graph whose
texts the hook fills in at runtime (the hook already intercepts `GetTranslation`). Hence [H].

**20. Caravan escort [S, T]** · M after contracts
Walk a real road with a merchant, with fights along the way and pay at the end.

**21. Master craftsmen [S, T]** · M after contracts and the school gear sets
Diagrams for superior gear come from contracts, and only a master NPC can forge them.

**22. Lairs [S, H]** · L · needs landmarks in the map index
Three fights and a boss at a ruin, a chest at the end, and a cooldown per player.

**23. Witcher schools [S, T]** · L · needs the community server for the claims
Wolf, Cat, Griffin, Bear, Viper or Manticore, chosen at level 10. Each school gets weekly goals and can claim nemeta by
hunting there.
Note: the choice needs a window to choose in; a quest conversation can do it.

**24. Elite monsters [S, H]** · L · needs the combat hook
Armored, frenzied, regenerating or venomous versions that are harder and drop better loot.

**25. World hunts [S, H]** · L · needs the community server, landmarks and the combat hook
A giant monster sits at a real landmark for a weekend. Everyone nearby fights it in their own fight, and the server pools
the damage into one health bar. Rewards go by contribution. No real-time networking is needed; the hook only sets the
monster's starting health.

**26. Weekly trial [S, H]** · L · needs the community server and the combat hook
The same monster with the same gear for everyone. The fastest kill tops the board and the top players get a reward.

**27. Recolored variants [T]** · L for the first, then S each · needs the game file pipeline
The bestiary already has colour variants (Green and Blue Forktail, Golden Katakan, Russet Shaelmaar). New ones could be an
Ancient Drowner, a Kikimore Queen boss or a Moonlit Werewolf.

**28. School gear sets with set bonuses [T, H]** · L · needs the game file pipeline and the combat hook; after schools
Existing sword and armor models recolored. The bonuses go through the same damage hook the oils already use.

**29. Runestones and glyphs [S, T, H]** · L · needs the combat hook
Dropped by monsters and socketed into gear: more damage against a family, a chance to burn, more herbs.
Note: the game has no socket screen; that is a new window [A] or a companion app screen.

## Tier 4: very large (client screens or whole systems)

**30. Alchemy rework [S, T, H]** · XL
Take inspiration from the alchemy system in Witcher 1: each ingredient carries a substance (Vitriol, Rebis, Aether,
Quebrith, Hydragenum, Vermilion), a recipe asks for substances so any ingredient carrying them will do, Albedo, Nigredo or
Rubedo add a bonus property, and potions need an alcohol base.
Note: the game's alchemy window asks for specific ingredients, so this changes the client's alchemy screen ([H] at least,
likely [A]). Potion tiers and alchemy discovery fit inside it.

**31. Alchemy discovery [S, T]** · L after the rework · needs the community server
Mix ingredients to find hidden recipes. The first player on the server to find one gets credited.
Note: free mixing needs a screen the game doesn't have ([A]) or the companion app.

**32. Toxicity [H, A]** · L to XL
Drinking too many potions has a cost. It needs a meter on screen.

**33. A witcher's keep [S, T, A]** · L in the companion app, XL in the game
Your own base, like Corvo Bianco. It has an alchemy lab (faster brewing), an herb garden (herbs grow in real hours) and a
trophy hall. Its screens could live in the companion app first.

**34. Dice poker [A]** · L in the companion app or on the web, XL in the game
The tavern game from Witcher 1 and 2, much smaller than Gwent, played in taverns against NPCs or other players.

## Tier 5: huge (months each)

**35. Season 2 [T, A]** · XXL · needs the rewritten Studio and the game file pipeline
A new story arc, written and tested in the rewritten Studio, with community voice actors.

**36. Alternate sign modes [A]** · XXL
An Aard sweep, an Igni stream, a Quen bubble. Players would love these, but they need new combat code and effects.

**37. Truly new monsters [A]** · XXL per monster
A Kayran, a dragon, a manticore, Wild Hunt hounds. Each needs a model, a rig, animations and fight behaviour. Spend it on
one flagship: a dragon world hunt.

**38. Gwent [A]** · XXL
A full Gwent is a game of its own. It could live in the companion app or on the web, with cards dropped by monsters. A
stretch goal.
