# КАРТА ШРИФТІВ NRFTW — де живе кирилиця і хто чим малює

> ## ФІНАЛЬНИЙ СТАН 2026-07-27 (вшито, перевірено 4 незалежними тестами)
>
> Розподіл і причини — окремий документ **`30_text/FONT_GROUPS.md`**.
> Одна команда вшиває все: `python 00_tools/pipeline/apply_all.py` (63 с).
> Одна команда відкатує: `python 00_tools/pipeline/restore_all.py`.
> Перевірка: `verify_all.py` (наскрізна) і `check_state.py` (знімок стану).
>
> | | Слот у бандлі | Слот у `resources.assets` | `m_Scale` | Цифри |
> |---|---|---|---|---|
> | **Fixel Display Light** | `NotoSerifCyrillic-Regular TMP` | `3335` | 0.7801 | `FixelDisplay-Regular` |
> | **Kyiv Region** | `NotoSerifCyrillic-Bold TMP` | `3333` | 0.8242 | `KyivRegion-Regular` |
>
> **Fixel — 22 шрифти:** уся родина `Arcon-*` (субтитри, описи, квести, стати,
> кнопки, підказки завантаження), `Liberation*`, `LucidaGrande`.
> **Kyiv — 17 шрифтів:** уся родина `friz-quadrata-*` (назви екранів і
> контейнерів, назви предметів, локацій, персонажів, акценти), `MarcellusSC*`,
> `standard-graf*`.
>
> 🔴 **Родину шрифтів не розривати.** У всіх `Arcon-*` спільний жирний варіант
> `ArconBold-Regular SDF - Variant`, у всіх `friz-quadrata-*` —
> `friz-quadrata-std-medium-bold SDF TMP - Variant`. Якщо частина родини піде в
> Kyiv, а частина у Fixel, то `<b>` усередині речення дасть чужу гарнітуру.
> Саме через це кнопковий `Arcon-RegularButton SDF` тепер у Fixel.
>
> 🔴 **`<b>` (811 тегів у перекладі)** перемикається на асет жирного накреслення.
> У ваніли в обох варіантів **порожній** `m_FallbackFontAssetTable`, тому
> кирилиця там бралася з глобального ланцюга TMP. Тепер кожен варіант веде в
> слот своєї родини. Позицію в порожній список вставлено без зміни розміру
> асета: **+4 запасних (48 Б) і −3 вільні прямокутники (16 Б × 3)**.
>
> 🔴 **Слоти `Regular SDF` / `Bold SDF` — асети ЧУЖОГО КЛАСУ** (`m_Script` →
> `Library/unity default resources` 19001, 38 полів замість 42). Гра їх ніколи не
> вантажила; посилання на них валить `TMP_FontAsset.ReadFontAssetDefinition`
> з `NullReferenceException` ще до головного меню. Не використовувати.
>
> 🔴 **Порядок відкату має значення.** `hide_base_punct` бекапить ЦІЛІ обʼєкти
> шрифтів, решта — по 8 байтів усередині них. Тому `restore_all` відкатує у
> **зворотному хронологічному** порядку (за часом створення журналів).
> Без цього таблиці ваг «відкатувалися» у проміжний стан — ця помилка вже
> траплялася. Аварійний ремонт: `restore_weights_from_originals.py`.
>
> Пунктуація (32 знаки) і цифри (10) вкладені в кожен слот за рахунок
> найрідкіснішої церковнослов'янщини з хвоста `U+A640..A69F`; у 49 базових
> шрифтах ці 40 символів приховано (`m_Unicode` → `U+E000+`). Тому цифра
> й кома всередині Kyiv-речення будуть Kyiv, а всередині Fixel-речення — Fixel.
>
> **Перевірено:** розміри всіх 9 файлів гри незмінні; чужий клас ніде не
> використовується; пари `<b>` збігаються за гарнітурою; латинських знаків у
> базових шрифтах 0 із 39; формат усіх кириличних асетів чистий; атласи
> зчитані з файлів гри й намальовані (`30_text/fonts_preview/з_файлів_гри.png`).
> Відкат перевірено окремо: повертає ваніль, `restore_weights_from_originals`
> після нього не знаходить жодної розбіжності з `originals/`.


Складено 2026-07-27 повним сканом **усіх** файлів гри без її запуску.
Інструменти: `00_tools/pipeline/scan_all_fonts.py`, `scan_font_usage.py`,
`scan_resources_v2.py`, `analyze_fonts.py`. Сирі дані: `30_text/fonts_scan/`.

Технічна база скану: блоки даних у бандлах гри **не стиснені**, тож кожен
`SerializedFile` читається потоково з диска через вікно-стрім. Пікова памʼять —
десятки МБ замість 7–20 ГБ. Гру закривати не треба.

---

## 1. Скільки шрифтів у грі насправді

| Файл | Шрифтових асетів | З них кириличних |
|---|---|---|
| `duplicateassetisolation` (бандл) | **52** | 4 |
| `resources.assets` (не бандл, **без typetree**) | **41** | 4 |
| `pooled_prefabs` | 6 | 0 |
| `static_scenes` | 2 | 0 |
| `qdb`, `qdb_binary`, `world_assets`, `static_assets`, `static_early`, `monoscripts`, `unitybuiltinassets`, `globalgamemanagers*`, `sharedassets0` | 0 | 0 |

Попередня сесія бачила **тільки 4 асети** в одному бандлі. Насправді шрифтових
асетів **101**, а кириличних — **8**, у **двох різних файлах**.

---

## 2. 🔴 Кириличні асети — усі 8 копій

### `duplicateassetisolation_...bundle` → `CAB-c96cdae22def2c264391645ea79e4d4c`

| Асет | `path_id` | Атлас-текстура | Хто на нього дивиться |
|---|---|---|---|
| **NotoSerifCyrillic-Regular TMP** | `-2444889057261992194` | `988337672387282686` | **20 базових шрифтів → ~13 000 посилань з UI. УВЕСЬ живий трафік гри.** |
| NotoSerifCyrillic-Regular SDF | `775181479505102588` | `318420984660887292` | 7 базових шрифтів, з них **жоден не використовується UI** |
| NotoSerifCyrillic-Bold TMP | `-5959213582716284887` | `-6802549710652944343` | **0 посилань — слот вільний** |
| NotoSerifCyrillic-Bold SDF | `-5519819465463294359` | `-3852689348299712919` | **0 посилань — слот вільний** |

### `resources.assets` (окремий, незалежний набір — його ніхто ніколи не патчив)

| Асет | `path_id` | Атлас-текстура | Хто на нього дивиться |
|---|---|---|---|
| **NotoSerifCyrillic-Regular TMP** | `3335` | `623` | **усі 17 «нових» шрифтів resources.assets → усе меню, завантаження, мультиплеєрні вікна** |
| NotoSerifCyrillic-Regular SDF | `3334` (старий формат) | — | 5 «старих» шрифтів (`MarcellusSC-Regular`, `friz-quadrata-std-medium SDF`, `Arcon-Regular SDF`, `Arcon-Regular-Loc SDF`, `LiberationSans SDF`) → `FontsStyleSheet`, `ActivityRewardPanel`, `MapChunkDetailsPanel`, `ActivityJournalEntryLabel`, `ActivityDetailsPanel` |
| NotoSerifCyrillic-Bold TMP | `3333` | `622` | **0 посилань — слот вільний** |
| NotoSerifCyrillic-Bold SDF | `3332` (старий формат) | — | запасний для `3334` |

Параметри всіх «нових»: **441 гліф, атлас 2048×2048, pad 10, кегль 112
(Bold 106), `m_Scale` 0.9, capLine 80 (Bold 76)**. Ідентичні в обох файлах.

---

## 3. 🔴 Чому Fixel не зʼявився ЖОДНОГО РАЗУ

`swap_cyrillic_fonts.py:38` і `font_test.py --slot SDF` кладуть Fixel у
`NotoSerifCyrillic-Regular **SDF**`, а Kyiv — у `...**TMP**`.

Повний скан посилань (13 200 посилань з UI на 32 базові шрифти) дає:

> **на `SDF`-асет не веде ЖОДНЕ живе посилання UI. Усі 13 200 ведуть на `TMP`.**

Тобто Fixel щоразу лягав у мертвий слот, а Kyiv — у той, через який іде вся гра.
Це повністю відповідає тому, що бачив користувач. **Конвеєр генерації, найімовірніше,
робочий — була переплутана адреса.**

Друга причина, чому підказки завантаження не змінилися жодного разу: вони живуть
у `resources.assets` (`hintTitle`, `hintText`) і беруть кирилицю з **власної**
копії `NotoSerifCyrillic-Regular TMP` (`path_id 3335`), якої не торкався ані
`swap_cyrillic_fonts.py`, ані `font_test.py` — обидва працюють лише з бандлом.

---

## 4. Хто чим малює — вимірено, а не вгадано

Кожен рядок — реальні `TextMeshProUGUI` з гри, з повним шляхом у ієрархії.
Усі без винятку ведуть у кириличний `TMP`-асет бандла.

| Базовий шрифт | Посилань | Що саме малює |
|---|---|---|
| `Arcon-Regular SDF` | **5 159** | описи предметів (`itemEffectDescription`, `itemEffectName`, `itemEffectAffix`), `description`, значення статів, квестові категорії |
| `Arcon-Regular Header` | **2 650** | **репліки NPC** (`playerHUD/playerSubtitlesView/npcDialogueDisplayType/npcDialogueText`), квестовий екран (`questTitle`, `questTextFull`, `questGiverName`, `questReward*`), лічильники, стати |
| `friz-quadrata-std-medium_clean SDF TMP` | **1 928** | підписи-мітки (`rowItemScalingLabel`, `resistanceLabel`, `gemsTitle`), заголовки сторінок меню |
| `friz-quadrata-std-bold-browndirt SDF` | **939** | назви слотів (`weaponslotName`), «Exalted»/рідкість, тости квестів |
| `Arcon-RegularButton SDF` | **776** | кнопки, зокрема **кнопки варіантів діалогу** (`multiChoiceButtons/choiceButton/text`), імена |
| `LiberationSans SDF` | 620 | іконки-гліфи керування, журнал (`playerJournal`), підказки кнопок, консоль |
| `Arcon-paragrapgh SDF` | 190 | описи (`descriptionText`), підзаголовки popup-ів, `Exit to Menu` |
| `friz-quadrata-std-medium-5870338ec7ef8 SDF_grey` | 190 | номери предметів, підпис інвентаря |
| `friz-quadrata-std-bold-clean SDF` | 153 | назви локацій (`areaName`), `Title`, теги проєктів |
| `Arcon-Bold SDF` | 104 | `BoonCategory`, `Rarity` у Горнилі |
| `friz-quadrata-std-medium-yellow SDF` | 88 | акценти, `Boon Title`, `titleText` |
| `Arcon-Regular SDFOutline` | 38 | нотифікації-оверлеї (`[IN] Subtitle`, `[IN] DescriptionField`) |
| `Arcon-Bold SDF_NoDepthTest` | 35 | мітки на іконках карти (`questMapIcon`), `ammoCount` |
| `friz-quadrata-std-italic-clean SDF` | 19 | опис бінда клавіш |
| `friz-quadrata-std-medium SDF TMP` | 12 | `realmname`, `pathName`, `Title` |
| `MarcellusSC-Regular_otf_Outline SDF` | 2 | `playerName` |
| `standard-graf_regular*`, `Arcon-Regular SDF Flavor`, `Arcon-Regular SDF_stats*`, `friz-quadrata-std-medium-gold SDF` | 1–50 | дрібні поодинокі елементи |
| `NotoEmoji-Regular SDF`, `NotoSerif*-Regular SDF 1`, `MarcellusSC-FightRegular` | 110 / 66 / 1 | емодзі та юридичні екрани (кириличного запасного не мають) |

**У `resources.assets` (меню, завантаження, мультиплеєр):**

| Елемент | Базовий шрифт |
|---|---|
| **`hintTitle`** («Hint») | `friz-quadrata-std-medium_clean SDF TMP` |
| **`hintText`** (текст підказки завантаження) | `Arcon-RegularButton SDF` |
| `realmName`, `expText`, `maxLevelText` | `friz-quadrata-std-bold-browndirt SDF` |
| `pathName`, `hardcoreText` | `friz-quadrata-std-medium SDF TMP` |
| `contentMessage`, `resyncLabel`, `placeholderMessage` | `friz-quadrata-std-medium_clean SDF TMP` |
| `resyncReason`, `buttonGlyph` | `Arcon-Regular SDF` |
| `actionDescription`, `skipRequestedLabel` | `Arcon-Regular Header` |
| `exitLabel` | `Arcon-paragrapgh SDF` |
| `exp`, `name` | `Arcon-Regular SDF_stats_value` |
| `levelValue` | `friz-quadrata-std-medium-5870338ec7ef8 SDF_grey` |
| `keybind` | `LiberationSans SDF` |

---

## 5. 🔴 Важливо для розподілу гарнітур

Первісний план був: «`Arcon-*` → Kyiv (інтерфейс), решта `friz-quadrata-*` →
Fixel (діалоги й лор)». Скан показує, що він спирався на хибне уявлення:

- **репліки NPC малює `Arcon-Regular Header`**, а не `friz-quadrata`;
- **описи предметів малює `Arcon-Regular SDF`**;
- `friz-quadrata-*` у грі — це переважно **мітки, заголовки й назви слотів**,
  тобто рівно те, що планувалося віддати Kyiv;
- `Arcon` сам по собі — **шрифт без засічок**, а `friz-quadrata` — із засічками.
  Тому англійський текст гри виглядає сучасним, а український — «російським
  Noto Serif»: засічкова кирилиця підставляється навіть під сансерифний Arcon.

Отже логічний розподіл під бажання користувача (мінімалістичний санс для основного
тексту, Kyiv для заголовків і акцентів) виглядає так:

| Гарнітура кирилиці | Кому віддати |
|---|---|
| **Fixel Display Light** (санс, основний текст) | `Arcon-*` — усі 12 варіантів: репліки NPC, описи предметів, квести, кнопки, стати |
| **Kyiv Region** (заголовки, акценти) | `friz-quadrata-*` (10 варіантів), `MarcellusSC*`, `standard-graf*` — заголовки, мітки, назви локацій, рідкість |

Це протилежно початковому плану — і саме тому варто узгодити з користувачем.

---

## 6. Чи можна точно обрати, де що рендериться

**Так, з точністю до окремого базового шрифту.**

Механізм: у кожного базового шрифта є список `m_FallbackFontAssetTable`, і перший
його елемент — `PPtr` на кириличний асет. Зміна цього посилання = перезапис
**8 байтів** (`m_PathID`); попередня сесія вже міряла — рівно 8 байтів на посилання,
розмір асета не змінюється.

Бюджет слотів (кожен зі власною атлас-текстурою, тому гарнітури не конфліктують):

| Файл | Слотів усього | Вільних зараз |
|---|---|---|
| `duplicateassetisolation` | 4 (`Regular TMP/SDF`, `Bold TMP/SDF`) | 2 (`Bold TMP`, `Bold SDF`) |
| `resources.assets` | 4 | 2 (`Bold TMP` 3333, `Bold SDF` 3332) |

Тобто **до 4 різних кириличних гарнітур одночасно** без створення нових асетів.
Для плану «Fixel + Kyiv» достатньо двох:

1. `Regular TMP` (бандл) ← гарнітура №1, `Regular SDF` (бандл) ← гарнітура №2;
2. переставити посилання 27 базових шрифтів бандла між цими двома;
3. те саме в `resources.assets`: `3335` ← гарнітура №1, `3333` (вільний Bold TMP)
   ← гарнітура №2, і переставити посилання 17 «нових» шрифтів;
4. `pooled_prefabs` (6 шрифтів) і `static_scenes` (2) посилаються **у бандл**
   через зовнішній `fileID`, тому окремої заміни не потребують — лише
   переставляння, якщо якийсь із них має отримати іншу гарнітуру.

### Порядок перевірки (щоб не гадати)

1. **Один тест:** Fixel у `Regular TMP` бандла **і** у `3335` `resources.assets`,
   рідні параметри (pt 112, pad 10, grad 11, атлас 2048² Alpha8, матеріал не чіпати,
   посилання не переставляти). Якщо Fixel видно у репліках NPC **і** в підказках
   завантаження — конвеєр підтверджено на обох джерелах.
2. **Другий тест:** Kyiv у `Regular SDF` + `3333` і переставляння посилань
   `friz-quadrata-*`/`Marcellus*` на них. Це вже фінальний розподіл.

---

## 7. ФІНАЛЬНИЙ РОЗКЛАД (14 286 посилань, усі файли просканіровані)

Одиниця перемикання — **базовий шрифтовий асет**. Їх 32 із живими посиланнями.

### → FIXEL DISPLAY LIGHT (простий текст)

| Шрифт | Посил. | Що малює |
|---|---|---|
| `Arcon-Regular Header` | 2 961 | **УСІ СУБТИТРИ**: `npcDialogueText`, `cinematicText`, `scriptureText`, ім'я мовця; стати, `menuDescription`, `durabilityText`, `itemTypeText`, туторіали |
| `Arcon-Regular SDF` | 5 343 | описи предметів (`itemEffectDescription/Name/Affix`), `itemName`, `description`, `descriptionText`, гроші, `recipeLearnedText`, `ResearchItemHintText` |
| `Arcon-paragrapgh SDF` | 242 | `description`, `descriptionText`, `locationText`, `restHintText`, `nothingLearned` |
| `Arcon-Regular SDF_stats` | 50 | `valueNotMeetText` |
| `Arcon-Regular SDF_stats_value` | 26 | `value`, `exp`, `name` |
| `Arcon-Regular SDF Flavor` | 50 | `unavailableText` |
| `Arcon-Regular SDF_GlyphsTest` | 15 | `Amount`, `bindingDescriptionText` |
| `Arcon-Regular SDFOutline` | 38 | нотифікації: `[IN] Subtitle`, `[IN] DescriptionField`, `Count` |
| `LiberationSans SDF` × 3 копії | 678 | іконки-гліфи керування, інпут-поля, журнал, консоль |
| `Arcon-Bold SDF` | 113 | `Text`, `labelCount`, `FocusCost`, `chestName` |
| `Arcon-Bold SDF_NoDepthTest` | 35 | мітки на іконках карти, `ammoCount` |

### → KYIV REGION (прикрашання)

| Шрифт | Посил. | Що малює |
|---|---|---|
| `friz-quadrata-std-medium_clean SDF TMP` | 2 201 | `rowItemScalingLabel`, `resistanceLabel`, `gemsTitle`, `Title`, `pageTitle`, `SettingTitle`, `itemNameText` |
| `friz-quadrata-std-bold-browndirt SDF` | 973 | `weaponslotName`, `characterName`, `playerName`, `realmName`, `header`, `[IN] Title`, `BoonName` |
| `friz-quadrata-std-medium-5870338ec7ef8 SDF_grey` | 195 | `ItemNumber`, `labelInventory`, `labelOptions`, `header` |
| `friz-quadrata-std-bold-clean SDF` | 153 | `count`, `Title`, `areaName` |
| `friz-quadrata-std-medium-yellow SDF` | 89 | `label`, `titleText`, `Boon Title` |
| `friz-quadrata-std-italic-clean SDF` | 28 | `label`, `bindingDescriptionText` |
| `friz-quadrata-std-medium SDF TMP` | 25 | `Title`, `realmname`, `pathName` |
| `friz-quadrata-std-medium-5870338ec7ef8 SDF` | 12 | `traitName`, `traitClassName`, `areaName` |
| `friz-quadrata-std-medium-gold SDF` | 4 | `text` (золоті акценти) |
| `MarcellusSC-Regular_otf_Outline SDF` | 2 | `playerName` |
| `MarcellusSC-FightRegular_otf SDF` | 1 | `FightText` |
| `standard-graf_regular SDF` + `Bitmap` | 2 | `primaryText` |

### ⚠️ Змішані — потрібне рішення

| Шрифт | Посил. | Конфлікт |
|---|---|---|
| `Arcon-RegularButton SDF` | 884 | кнопки (`text`, `name`, `choiceButton`) **разом із** `hintText` підказок завантаження, `message`, `longerMessage`, `descriptionText` |

### Лишити Noto (кирилиця не потрібна)

`NotoEmoji-Regular SDF` (110) — емодзі; `NotoSerifJP/KR/SC/TC-Regular SDF 1` (74) —
юридичні екрани CJK.

---

## 8. Що НЕ підтвердилось / лишилось

- `world_scenes` (3,18 ГБ серіалізованих даних, 4154 ноди) сканується довго;
  на момент складання карти пройдено ~45 %. Нових **шрифтових асетів** там не
  знайдено (тільки посилання на бандл), але фінальні цифри посилань уточняться.
- `m_Script` частини шрифтів `resources.assets` веде у
  `Library/unity default resources` — це **старий формат TMP**-асета, який
  не читається новим typetree. Їх 15, вони другорядні (стилі, кілька панелей),
  але при заміні гарнітури їх треба або оновити сирим записом, або лишити Noto.
- Матеріалів (`material`) у кириличних асетів у typetree **немає** (`None`) —
  ще одна причина не чіпати `_GradientScale`.
