# International humour research and corpus guide

Research and implementation date: 2026-09-27. The user selected France, Armenia, Italy, Germany and Norway and delegated the choice of cultural subjects. Spain remains in the release to satisfy the original Spanish-language request.

## Collection matrix

Each main collection targets 200 individually authored records in each of the app's nine primary categories, for 1,800 per collection and 10,800 total. The categories are wholesome, office-proper, dad, kid-safe, nerd, surreal, dark, edgy and puns. Installed counts, moderation eligibility and import results are recorded separately in [the coverage report](../Testing/2026-09-27-international-corpus-coverage.json).

| Main collection | Language | Researched settings and distinctions | Detailed brief |
| --- | --- | --- | --- |
| France | French (`fr`) | Boulangeries, café life, books, school conventions, local public administration and everyday regional settings; French idioms and sound play | [France](2026-09-27-french-humor-contexts.md) |
| Armenia | Eastern Armenian (`hy`) | Kochari, lavash, duduk, weaving, family hospitality, Yerevan/Cascade, Gyumri, Matenadaran and Vardavar; preserve Armenian script and distinguish Western Armenian | [Armenia](2026-09-27-armenia-humor-contexts.md) |
| Italy | Italian (`it`) | Neapolitan pizzaiuolo craft, Sicilian puppets and sweets, Bologna porticoes, Ligurian pesto/focaccia, Puglian pasta/trulli, Trieste coffee vocabulary and Cremona violin making | [Italy](2026-09-27-italian-humor-contexts.md) |
| Germany | German (`de`) | Bread culture, gardens, school cones, workplace routines and German–Austrian lexical differences; German is pluricentric | [Germany and Austria](2026-09-27-german-austrian-humor-contexts.md) |
| Norway | Norwegian Bokmål (`nb`) | Dugnad, cabin life, outdoor recreation, packed lunches, May17, coastal travel and friendly Nordic encounters; Bokmål does not stand in for Nynorsk or Sámi | [Norway and Nordic neighbours](2026-09-27-norway-nordic-humor-contexts.md) |
| Spain | Spanish (`es`) | Regional tapas and dishes, plazas, Córdoba patios, Fallas, Sant Jordi, New Year traditions and language-specific wordplay; Spain's other languages are distinct | [Spain](2026-09-27-spanish-humor-contexts.md) |

The [initial cross-language memo](2026-09-27-humor-localization-research.md) provides the broader research framework and primary-source links. The six expanded briefs link institutional language resources, cultural heritage inventories, scholarly work and official cultural/tourism sources. These sources substantiate settings, language variation and customs, not the truth of invented comic events or a national personality.

## Neighbour humour

German-language scenes can involve Austria. Bokmål scenes can involve Sweden or Finland. These use genuine contextual differences—regional food words, fika, sauna, shared trips and sporting rivalry—with fictional speakers and reversals. A country tag describes the scene; it is not a claim about the author or every resident.

Austria, Sweden and Finland are secondary country contexts on the same joke records. They can be selected independently in the app, including together with a reading language. They are not separate quota collections or Swedish/Finnish language editions. Their counts overlap with the main collections and cannot be added to the unique total. Regional subjects within each collection are researched examples, not an exhaustive taxonomy of all cultures in a country.

## Authorship and review

The new texts were authored directly in their target languages. Source joke anthologies were not scraped. The original 1,000 starter records retain their text and IDs; expansion batches supply the remaining category deficits. Scripts assemble metadata, validate records and count coverage; they do not generate variants by substituting country names or nouns into joke templates.

All generated records remain labelled `generated`/AI-authored. Machine checks cover schema, Unicode-normalized exact duplicates, stable identifiers, primary categories, secondary country codes and installed coverage. Similarity screening helps locate close textual reuse but cannot establish global originality, comedic quality or native linguistic naturalness. No human native-speaker review or cultural endorsement is claimed. Editors can revise individual records and record native review through the application's editorial workflow; imports preserve existing moderation and editorial decisions.

## Exploring the result

Open the public Explore page and expand **Joke languages**. Collection shortcuts choose a matching language/country/culture; the three selectors can also be combined independently. Choose a category to narrow the result further. The URL is shareable, preferences persist in that browser, and switching selection clears accumulated cards from the previous selection. Incompatible combinations show an empty result instead of switching languages silently. Interface labels remain English, while joke text and native language names use the selected language.

See [API and frontend behavior](../API/International_Discovery.md), [corpus/import documentation](../../jokes/fixtures/international/README.md), and [verification evidence](../Testing/2026-09-27-international-discovery.md).
