# JokesFor: language, place, and cultural-context research

Research date: 2026-09-27. Decision memo for international joke discovery and corpus production. Primary research scope: Spanish in Spain, French in France, German in Germany, Eastern Armenian in Armenia, and Italian in Italy. Additional country and community targets must be named explicitly; these five baselines do not represent the complete Spanish-, French-, German-, Armenian-, or Italian-speaking worlds.

Evidence labels: **Verified source** identifies findings from the linked institution or research paper. **Recommendation** identifies product/editorial judgment. **Unmeasured** identifies hypotheses that require audience testing. Original examples below are newly composed AI-assisted drafts, with no claim of native-speaker review, cultural endorsement, global novelty, or proven funniness.

## Situation and decision

Build three independent discovery dimensions: **language of the joke**, **country/place context**, and **cultural collection**. Preserve a separate interface-language preference. A person should be able to use an English interface to find French-language jokes set in Canada, or Armenian-language jokes about life in France. A country selection must not silently change the language, and a language must not imply a nationality.

JokesFor's supplied business baseline reports 173 jokes, one language, zero users/revenue, and untested demand. This memo did not remeasure those numbers. The configured `/obs-recall` workflow was read, but its required `~/.obsidian-Codex.env` and project `.Codex/obsidian.env` files were absent in this research environment; the referenced vault notes were therefore not retrieved. Baseline strategy and tenets here are supplied context, not fresh vault or production measurements. Implementation and current catalog counts must be verified separately.

The requested corpus is **at least 200 per category across multiple countries/cultures for each named language**. A thousand jokes, or 200 per language, would not satisfy that clarified request. Record the actual target combinations in a manifest before claiming completion. Country and culture are overlapping classifications, so multiplying every available label creates imaginary requirements and encourages irrelevant tagging.

The recommended approach follows Child Safety → Content Quality → Search Utility → Retention → Creator Value → Revenue. International discovery closes a real language-access gap; its desired outcome is more Weekly Active Searchers finding usable material. More generated rows alone cannot establish that outcome.

## Options and recommendation

| Option | What it delivers | Main limitation |
| --- | --- | --- |
| Translate one English corpus into five languages | Fast parallel text and simple translation links | Wordplay and cultural reference failures; repeated premises; country coverage cannot be inferred from translation |
| Generate large country-labelled batches immediately | Many draft records | Labels can become stereotypes; numeric completion conceals weak language, near-duplicates, and unreviewed content |
| Author and curate against explicit language/place/collection/category targets | Auditable coverage and a path to useful, credible discovery | Requires editorial throughput, provenance, and review status to be first-class data |

**Recommendation:** implement the third option, with AI-assisted original drafting where useful. Build import, coverage reporting, filtering, and review workflows together. Imported drafts can support editorial work immediately; public availability and native review must remain independently truthful. Defer on-demand joke generation, automatic cultural inference, dialect conversion, translated audio, and a translation marketplace until the initial discovery and content-quality loop is measured.

Pilyarchuk's 2024 study examines wordplay translation using 526 humorous acts from a television season and translations including German. It finds that translator creativity may matter more than language proximity. This supports testing a joke's mechanism in its target language; it does not establish audience preferences for entire countries, or guarantee that an LLM can reproduce the results. [European Journal of Humour Research: “Wordplay-based humor: to leave it or to translate it, that is the question,” abstract and methodology](https://europeanjournalofhumour.org/ejhr/article/view/915).

## Representation and navigation

Use BCP 47 for actual language varieties, ISO country codes for place contexts, and controlled application identifiers for collections. BCP 47 region subtags refine a language variety when that distinction matters. They are not an ethnicity or culture classification. Avoid flag-only language buttons. Native-language names plus region or variety labels are clearer. [W3C, “Choosing a language tag,” decisions 1–4](https://www.w3.org/International/questions/qa-choosing-language-tags).

| Baseline | Language code | Optional locale | Explicit visible label | Important boundary |
| --- | --- | --- | --- | --- |
| Spanish, Spain | `es` | `es-ES` | Español · España | Spain contains multiple languages and Spanish varieties; Spanish is also used outside Spain |
| French, France | `fr` | `fr-FR` | Français · France | French-language content is not automatically about France |
| German, Germany | `de` | `de-DE` | Deutsch · Deutschland | German-language content can have Austrian, Swiss, or other contexts |
| Eastern Armenian, Armenia | `hy` | `hy-AM` | Հայերեն · Արևելահայերեն · Հայաստան | Store the Eastern variety explicitly; `hy-AM` alone is not a complete linguistic/editorial description |
| Italian, Italy | `it` | `it-IT` | Italiano · Italia | Standard Italian is not a promise of regional-language coverage |

Western Armenian has the separate registered language subtag `hyw`; it must not be presented as a font, accent, or country setting for `hy`. IANA's `hy` record describes Armenian and points to `hyw`; `Armn` is its suppressed script, so adding `-Armn` normally adds no distinguishing information. [IANA, Western Armenian registration](https://www.iana.org/assignments/lang-subtags-templates/hyw.txt), [IANA, Armenian registration](https://www.iana.org/assignments/lang-subtags-templates/hy.txt).

Recommendations for the narrowest useful model:

- **Text edition:** language, optional locale/variety, setup, punchline, optional explanation, stable ID, and an optional link to the original/adapted edition. Distinguish adaptation from literal translation.
- **Place context:** zero or more country/region associations describing the joke's setting or relevant context. This is not the author's residence or the viewer's inferred location.
- **Cultural collection:** editorially named, described, and scoped; for example, Armenian letter play or everyday life in a specified city. It may span countries and languages. An everyday joke need not claim cultural specificity.
- **Content attributes:** topic/category, mechanism, age/content classification, provenance, and review state. Keep mechanisms such as wordplay and absurdity distinct from subjects such as school and food.
- **Preferences:** interface locale and joke-language preference are separate. Store explicit user choices, rather than inferring cultural identity from names, location, or browsing.

A useful discovery sequence is language → optional place/collection → category, with removable filter chips, actual available counts, a clear reset, URL persistence, and a truthful empty state. Restrict results to the requested language unless the user opts to broaden. Explain any broadening before showing it. Preserve the original wording and provide an optional explanation after the reveal for language learners; a translated explanation is not a replacement for a broken punchline.

Future candidates such as Spanish in Mexico, French in Canada, German in Austria or Switzerland, Italian in Switzerland, and Armenian diaspora contexts require their own named targets and editorial checks. They are extensions to research, not claims of support established by this memo. A diaspora place does not identify its speakers' Armenian variety.

## Spanish: language mechanics and context

**Verified source:** RAE/ASALE describes *seseo* and *ceceo* and the distribution of pronunciation contrasts within Spain and beyond. Pairs involving `s` versus `c/z` do not have the same sound relationship for every Spanish speaker. Consequently, a sound-based punchline that works in one variety cannot be labelled universal Spanish without checking it. [RAE/ASALE, “El seseo y el ceceo,” pronunciation and orthographic consequences](https://www.rae.es/buen-uso-espa%C3%B1ol/el-seseo-y-el-ceceo).

The Instituto Cervantes explicitly treats games, riddles, and wordplay as playful language use. Its teacher-training material also identifies lexical and sociocultural difficulty when working with humor. These establish useful teaching considerations, not that every short joke is suitable for beginners. [Cervantes, CEFR chapter 4, “Usos lúdicos de la lengua”](https://cvc.cervantes.es/ensenanza/biblioteca_ele/marco/cap_04.htm), [Cervantes Prague, teacher workshops, humor session](https://praga.cervantes.es/es/profesores_de_espanol_espanol/encuentros_profesores_espanol/xii_encuentro_2017/talleres-paralelos.htm).

**Recommendations:** preserve `ñ`, accents, and opening question/exclamation marks. Choose a consistent variety for vocabulary and forms of address. Test homophones against the intended pronunciation; mark sound-dependent jokes accordingly. Build on specific scenes—an apartment lift, a classroom, a local library, a shopping trip—with recognizable dialogue. Research a named custom before making it the mechanism. Do not use lazy/fiery national-character claims, or treat all of Spain as a single regional culture. A scene in Spain can be ordinary life without explaining Spanish identity.

Original drafts:

1. «Le pedí al calendario que me hiciera un hueco. Arrancó el martes.» Mechanism: literal interpretation of *hacer un hueco*. General Spanish-language context; no country-specific claim.
2. «En el ascensor de mi bloque han puesto una pantalla con consejos de productividad. Ahora hasta subir al tercero cuenta como formación.» Mechanism: everyday incongruity. Suggested Spain-context edition; not an account of a national trait.

## French: sound, register, and more than one francophone context

**Verified source:** the Office québécois de la langue française describes *calembour* as humor arising from simultaneous meanings and discusses homophonic and near-homophonic substitutions. That account is useful linguistic evidence across French-language work; it is not evidence that a particular vocabulary item is interchangeable between France and Quebec. [OQLF, “calembour,” definition and notes](https://vitrinelinguistique.oqlf.gouv.qc.ca/fiche-gdt/fiche/8869711/calembour).

France's Ministry of Culture explicitly recognizes linguistic plurality as part of France's cultural identity. A French-language France collection should therefore not claim to represent every language or community in France. [Ministère de la Culture, “Langue française et langues de France”](https://www.culture.gouv.fr/thematiques/langue-francaise-et-langues-de-france).

**Recommendations:** read puns aloud as well as visually. Distinguish spelling play from sound play; context must make the two meanings recoverable. Keep `tu`/`vous`, elision, apostrophes, accents, and dialogue register coherent. Test the selected font and line wrapping with French punctuation and spacing. Use clearly fictional everyday scenes rather than “the French are…” premises. Avoid assigning one attitude toward satire, religion, or politics to all francophone readers. For additional countries, check local vocabulary with a reviewer for that locale instead of merely substituting a city name.

Original drafts:

1. «Ma cafetière connectée promet un café allongé. Après vingt minutes de mises à jour, je comprends mieux le programme.» Mechanism: a coffee term and prolonged waiting. France-context candidate requiring local review.
2. «Mon agenda m'a proposé un créneau pour ne rien faire. Il a fallu trois réunions pour le valider.» Mechanism: institutional absurdity. General French-language workplace context.

## German: word formation, precise meaning, varied comic forms

**Verified source:** the Leibniz Institute for the German Language describes productive word formation, including compounds and meaningful constituent combinations. That supports compound reinterpretation as an editorial technique, provided the invented reading is intelligible. [IDS grammis, “Wortbildung,” definition and explanations](https://grammis.ids-mannheim.de/terminologie/297).

Goethe-Institut's *Komplett Kafka* teaching material discusses wordplay, irony, satire, slapstick, stand-up, and absurdity. It provides a direct counterexample to the idea that German-language humor should be reduced to a single “dry” national style. The materials are teaching resources, not an audience-preference survey. [Goethe-Institut, *Komplett Kafka*, teacher guide, Plakat 13](https://www.goethe.de/resources/files/pdf328/didaktisierung_komplett-kafka_a2-b1-v11.pdf).

**Recommendations:** retain umlauts, `ß`, noun capitalization, and idiomatic case and verb placement. A compound must carry a plausible initial reading before being reinterpreted. Check German inflection rather than applying English word-order templates. Keep `du`/`Sie` consistent. Treat German in Switzerland or Austria as separate editorial targets when the text depends on local vocabulary or conventions. Use everyday systems, household objects, games, and misunderstandings without implying that all Germans are humorless, rigid, or bureaucratic.

Original drafts:

1. „Mein Drucker verlangt eine Bestätigung, bevor er die Testseite druckt. Offenbar wird heute mein Vertrauen getestet.“ Mechanism: reinterpretation of a test page as a test of the user.
2. „Meine Zimmerpflanze hat jetzt eine Erinnerungs-App. Seitdem gieße ich regelmäßig mein Handy.“ Mechanism: a misplaced response to a reminder. General German-language context; no country-specific claim.

## Armenian: varieties, script, and community specificity

**Verified source:** Armenia's intangible-cultural-heritage inventory, in a text attributed to the National Academy of Sciences' Institute of Language, describes substantial dialect diversity and Eastern and Western groupings. A single “Armenian culture” field would conceal that diversity. [Armenian intangible-cultural-heritage inventory, “Dialect”](https://int-heritage.am/en/dialect/).

UNESCO's Armenian letter-art entry documents uses of Armenian letters beyond ordinary writing, including riddles and decorative practice. This supports an optional letter-play collection as a researched cultural context; it does not imply that Armenian humor generally consists of alphabet jokes. [UNESCO, “Armenian letter art and its cultural expressions”](https://ich.unesco.org/en/RL/armenian-letter-art-and-its-cultural-expressions-01513).

Unicode specifies Armenian tonal punctuation whose placement relates to the relevant vowel rather than merely the sentence end. Store proper Armenian Unicode text, preserve punctuation, and visually test rendering and selection. [Unicode Standard 17.0, chapter 7, Armenian punctuation](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-7/).

**Recommendations:** use an explicitly Eastern Armenian baseline for Armenia-targeted initial texts. Record orthographic convention separately where needed; do not automatically equate a diaspora location with Western Armenian or convert between varieties by transliteration. Ask the reviewer to assess grammar, everyday register, pronunciation-dependent wordplay, and the text's claimed context. Latin transliteration may be optional explanatory metadata, but it should not replace the original script. Avoid invented “traditional Armenian jokes,” imitation accents, conflict or genocide premises in family-oriented seeding, and relatives-as-national-character templates. Modern everyday Armenian life deserves breadth beyond food and hospitality.

Original Eastern Armenian draft candidates, especially requiring fluent local review:

1. «Երևանի ավտոբուսում հեռախոսս հայտնեց՝ «Հիշողությունը լիքն է»։ Մեկը խորհուրդ տվեց՝ «Հին կանգառները ջնջիր»։» Intended mechanism: phone memory interpreted as a record of bus stops. Intended Armenia/Yerevan context; newly composed fiction.
2. «Գրեցի «հանգիստ» բառը ու կախեցի գրասենյակի դռնից։ Հիմա բոլորը ներս են գալիս՝ հարցնելու, թե երբ է սկսվում։» Intended mechanism: the attempt to obtain quiet generates interruptions. General Armenian-language workplace context.

These are not Western Armenian editions. Their presence is not evidence that a native Armenian reviewer has validated them.

## Italian: standard language, idiom, and regional specificity

**Verified source:** Accademia della Crusca's educational work explicitly distinguishes Italian, dialects, and local varieties and treats their relationship as dynamic. Its published work on *ludolinguistica* offers a basis for language play as an educational activity. Neither source establishes one national humor preference. [Crusca Scuola, “Visitare l'Accademia della Crusca,” “Dialetti e lingua”](https://www.cruscascuola.it/contenuti/visitare-laccademia-della-crusca/1938), [Anthony Mollica, “Insegnare/Imparare l'italiano? È un gioco di parole!,” Accademia della Crusca](https://accademiadellacrusca.it/sites/www.accademiadellacrusca.it/files/articoli/2011/10/03/Articolo_Mollica.pdf).

**Recommendations:** begin with natural contemporary standard Italian. Check articles, gender agreement, clitic placement, apostrophes, accented vowels, and `tu`/`Lei` consistency. Use idioms only when the intended second meaning is recoverable. Regional or community collections require relevant review; writing standard Italian in a Naples setting does not make the text Neapolitan-language content. Avoid mafia, laziness, temperament, or gender-role stereotypes as country shortcuts. Local objects such as a moka can furnish a scene, but diversify beyond food and tourist imagery.

Original drafts:

1. «La moka nuova si collega al telefono. Prima del caffè devo accettare tre biscotti: nell'app li chiamano cookie.» Mechanism: computing vocabulary recast as a coffee accompaniment. Italy-context candidate, with intelligibility of the borrowed term to be checked.
2. «In biblioteca ho chiesto un libro per imparare a decidere in fretta. Mi hanno proposto cinque edizioni. Sono ancora lì.» Mechanism: the promised solution recreates the problem. General Italian-language context.

## Corpus production, provenance, and acceptance

Create one row per required coverage target: `(language/variety, place scope, cultural collection, category, minimum=200)`. Use only explicitly supported combinations. If the eventual scope were five languages, two named contexts per language, and five categories per context, the target would be 10,000 category-context memberships. That is an **illustration**, not the agreed scope. A requirement for 200 unique jokes in every intersection is materially different from 200 per language and must remain visible in the manifest.

For each target, report drafted, imported, duplicate-rejected, reviewed, approved, and publicly available counts separately. Never treat template expansions, changed names, or the same joke tagged into many collections as evidence of an equally large independent corpus. Track a premise/origin ID across adaptations; count distinct eligible joke IDs within a target and disclose overlap between targets.

Recommended production process:

1. Write a short brief for each target: intended readers, everyday contexts, accepted variety, topic, excluded stereotypes, and mechanism mix. Pair country-specific requirements with actual researched contextual features.
2. Compose small original batches in the target language. Vary narrative structure, situation, protagonist, and comic mechanism. Do not pad quotas by swapping nouns, occupations, place names, or numbers into one pattern.
3. Store provenance: stable external ID, origin type (`original_ai_assisted`, commissioned, contributor, or licensed), author/credit where known, drafting batch and revision, source/permission record if applicable, adaptation links, and review status. An original draft should not carry a fabricated source citation.
4. Validate Unicode, required fields, language/locale compatibility, taxonomy, content labels, and counts. Normalize for duplicate comparison while preserving display text. Check near-duplicates and shared premises, not only exact hashes.
5. Review naturalness, recoverable punchline, category fit, factual cultural reference, target context, and suitability for the intended audience. Record who reviewed which edition and what was changed. A model evaluation can aid triage; it must not be labelled native human review.
6. Publish only through the application's explicit content workflow. Keep draft and public counts distinguishable. Collect corrections and withdraw problematic editions without deleting their provenance.

Research sources are for linguistic and cultural background, not a joke-mining license. Do not import institutional examples, joke websites, films, or a comedian's material into the corpus merely because they are readable online. Where externally licensed material is used, retain the exact license, author, URL, and adaptation permissions. Creative Commons distinguishes commercial-use, noncommercial, share-alike, and no-derivatives conditions; they are not interchangeable. [Creative Commons, “The CC Licenses”](https://creativecommons.org/cc-licenses/).

Child-safety and content-quality recommendations apply equally across languages: review meaning and implied targets, not only an English profanity list; do not turn absent language-specific moderation into an automatic “safe” classification. Preserve existing age restrictions and reporting behavior through locale changes. Record cultural interests as user-chosen content preferences, without deriving ethnicity or religion. These are implementation requirements to verify, not claims that the existing system already meets them.

## Metrics, risks, and next actions

| Recommendation | Tenet | Measurement | Current-system implication |
| --- | --- | --- | --- |
| Explicit language/place/collection filters | Search Utility | Search success, zero-result rate, reformulation rate by requested locale | Verify all discovery paths apply the same filters and pagination semantics |
| Target-language editorial review and premise deduplication | Content Quality | Approval rate, duplicate rate, native-review coverage, corrections per locale | Generated/imported counts must remain distinct from reviewed supply |
| Preserve age/content restrictions across locale switches | Child Safety | Policy-eligible results and report outcomes by locale | Test localized paths against existing restrictions |
| Persist chosen filters and support shareable results | Retention | Repeat searchers and D7 retention by locale; Weekly Active Searchers overall | Do not claim retention uplift before users exist |
| Retain provenance and adaptation links | Creator Value | Attribution completeness and resolved rights/correction requests | Avoid promising creator payouts or compensation rails from this feature |

The principal risks are poor naturalness at scale, culturally empty country tags, a large near-duplicate corpus, and conflating draft volume with public quality. Language-specific demand and conversion remain unmeasured. No recommendation here changes pricing, certifies PMF, or turns international reach into a revenue forecast.

Next actions are to resolve the exact target matrix; implement its data and filter contract; author against it; produce a machine-readable count report; verify age, provenance, and visibility behavior; and evaluate search success with readers in each initial locale. An initial human evaluation can use a small sample, but sample approval must not be represented as review of every item.

Owner decisions still needed for corpus acceptance: the additional countries/communities for each language, the complete category list, whether quotas apply to every named intersection, and whether any overlapping jokes may count toward more than one collection. These decisions should not block independent implementation of the representation and navigation contract.

Vault notes to update after implementation and measured verification: `JokesFor/Features/international-joke-discovery` (new), `JokesFor/Research/humor-localization` (new), `JokesFor/Technical/content-taxonomy-and-provenance` (new), `JokesFor/Runbooks/localized-corpus-review` (new), `JokesFor/Context/current-state`, `JokesFor/Context/open-gaps`, `JokesFor/Business/goals-and-metrics`, `JokesFor/Business/compliance-framework`, and `JokesFor/Business/pitch-vs-system-drift`. No vault update was performed by this research task.
