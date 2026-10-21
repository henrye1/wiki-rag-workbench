# Wiki schema
Schema version 3.12
This document tells the wiki maintainer (the LLM) how this wiki is structured. Edit it to fit the domain.

## Purpose
A persistent, interlinked knowledge base compiled from the published standard text, organised to clause level. Pages are written and maintained by the engine; humans curate sources and ask questions. No page body is hand-written.
Each claim is a concise statement of what its source says, linked by character offsets to the passage it rests on, so it can always be traced back to the original wording. A claim may be shorter than its source but never changes its meaning: it keeps who the statement applies to and whether it is required, permitted, expected or only illustrated. Where the two differ, the source wording governs.
Every claim is labelled by kind — requirement, application guidance, example, or editorial — and a claim is stated as an obligation only where its source wording is one ("shall", "must", "is required to"). Claims that cannot be supported by their source are kept off the pages.
Every sentence on every page that states something from a source ends with the clause it comes from, written [[source-<source-name>|<clause reference>]], on every page without exception. Sentences about the wiki itself are the only exception, as set out in Writing page text.
Four further rules apply on every page without exception. A sentence from application guidance, an example, an editorial note or the basis for conclusions opens with what it is: "Application guidance states ...", "In Example <n>, ...", "The editorial note states ..." or "The <issuer> concluded ...". A sentence from the Standard's own paragraphs has no opener, whatever its force. Every source paragraph is written up in full: its numbers, thresholds, time periods, conditions and exceptions are stated, and a paragraph with lettered or numbered parts keeps every part with the source's own lettering ((a), (b), (i), (ii)). All fifteen section pages are created on every ingest, including those that end up empty. A link points only to a page that exists; other standards and documents are written as plain text.

## Page types
There are seven page types, and the vocabulary is fixed rather than minted per document, so the same structure exists for every standard and nothing drifts between ingests. Every page is created from a controlled list or a saved question, never from free text or from whatever a source happened to say.
Only topic pages hold claims. Every other page type is composed: it holds no claims of its own and is built from links to claims already filed, so nothing is stated twice in different words. Any page that is not a requirement says so.
- overview — the single top-level page, slug overview. Lists the fifteen sections with what each covers and whether it holds requirements or non-authoritative material. It is the only page the librarian reads when choosing where to look. No second top-level page is created, under the framework slug (e.g. ifrs-9) or any other name.
- source — one per registered source document, slug source-<name>. States what the document is (issuer, edition, part), its authority sentence transcribed verbatim, and which sections it informs. Dates and counts are stated only when the engine supplies them; they are never estimated. Key takeaways are at most five of the source's own highest-ranked claims, linked, not a written summary. The source page holds only these parts; it has no other sections.
- entity — a specific, named thing the standard refers to: another standard or interpretation, an issuing or interpretive body, or a document. Lists every claim that names it and the nature of the link (scope boundary, disclosure partner, measurement input). Created only from a controlled list of designations. Parties in examples (Bank A, Entity B) are not entities; they stay inside their example claims.
- concept — a term, rule or method the standard uses: a defined term, a named rule such as a rebuttable presumption, or a method. States whether the standard defines it, presumes it or leaves it open, links to its definition in Definitions rather than copying it, and links to every claim that uses it. Created only from terms recorded in Definitions or from a controlled list of named rules.
- topic — one of the fifteen fixed sections. Created from the vocabulary before any claim is written, so an empty section is a page that says it is empty, not a missing page. A claim that names a section outside the fifteen is discarded and counted, never defaulted onto whichever page happens to be first.
- comparison — a side-by-side view of two or more things from the standard (e.g. two measurement bases; a requirement and the example that illustrates it). Each row links to the claims it rests on.
- synthesis — an analysis or answer filed back from a query. Records the question and date, and is never used as a source for new claims.

## The fifteen sections
Each brief states what belongs on the page, what to hand off and where, the boundary against the section most likely to be confused with it, and what makes a weak source for it. The whole of each brief is sent to the extraction model, which is what routes a claim to a page.
Every claim filed to any section carries its statement kind — requirement, application guidance, example or editorial — read from the clause its quote sits in. Editorial annotations, and material the issuer publishes alongside the standard but outside it (such as agenda decisions or interpretive notes), are never filed as requirements, whichever section they bear on.
### 01. Overview and status
- Belongs here: what the standard is and where it stands — objective as the issuer states it, issue history, each amendment with its date and subject, effective date of the version documented, what it superseded and what has superseded it, the structural map of its published parts, and the authority sentence transcribed verbatim ("X is set out in paragraphs ... and ...") (or, where an appendix states its own authority, that statement, e.g. "This appendix is an integral part of the Standard").
- The authority sentence decides which parts bind. Worked examples and illustrations read their authority from it; record it exactly, because a misread here misfiles every example.
- For an interpretation: the question it resolves and the standard it interprets, stated before anything else. That question is the point of the document.
- Hand off: transition mechanics -> Transition and effective date (this section holds the dates, that one holds the procedure). What the standard sits alongside -> Interactions and application in practice.
- Not the overview page: this is a topic section holding claims; the overview page is the index of the fifteen and holds none.
- Weak source if: the authority sentence is paraphrased rather than transcribed, or the amendment chronology stops short of the edition being documented.
### 02. Scope and applicability
- Belongs here: whether the standard applies to something. Inclusions and exclusions, each exclusion named with the standard that picks it up instead, entities or transactions exempted, recognition exemptions taken by election, elections that move an item into or out of scope, and items sitting outside the main requirements but inside one sub-model — named here with the reason, treated elsewhere.
- The population of each sub-model is recorded here as well as in the section that owns it (for example, the items to which one set of requirements applies), so that scope questions can be answered from one place.
- Exclusions and their exceptions keep their conditions word for word ("except", "unless", "other than"). An exception to an exclusion is recorded with the exclusion it qualifies.
- Hand off: how this standard relates to another once both apply -> Interactions and application in practice. What the thing being accounted for actually is -> Unit of account. Treatment of anything in scope -> the functional section that owns it.
- Boundary: scope decides WHETHER the standard applies; unit of account decides WHAT it applies to.
- Weak source if: an exclusion is recorded without naming where the excluded item goes, or a partial-scope item is described without a pointer to the section holding its treatment, or a sub-model's population is listed incompletely.
### 03. Definitions
- Belongs here: every term the standard defines, verbatim with its reference; terms defined in the body rather than the glossary, flagged as such; and — equally important — terms of art the standard deliberately leaves undefined, recorded explicitly as open. Where another standard defines the same word differently, note it and link. Where this standard borrows a glossary wholesale, record the borrowing rather than leaving the section blank.
- Each defined or open term creates or updates its concept page, which links back to the definition here.
- Wording that appears only in an editorial annotation is not a definition and is not recorded here.
- Hand off: the entity's decision on an open term -> Judgements, estimates and policy choices. Terms the firm or a client defines -> methodology/research or client working papers, never here.
- Weak source if: a term of art is used without recording whether the standard defines it, presumes it, or leaves it to the entity. Definitional drift is the commonest real contradiction, and an unmarked open term is where it starts.
### 04. Unit of account
- Belongs here: the level at which the standard is applied — how a contract, asset or population is divided, combined or grouped before anything else happens to it. Identifying the item; separating a contract into components; combining items into one; grouping or aggregating into the level at which a test is performed; the basis for allocating an amount across those components or groups; the level at which any later test must be applied; criteria for changing the unit afterwards.
- Hand off: whether the standard applies at all -> Scope and applicability. Which category the item falls into once identified -> Classification and categorisation. How the allocated amount is computed -> Measurement. The trigger for a test performed at this level -> Impairment and write-downs.
- Boundary: this section asks WHAT IS THE THING. Classification asks WHICH BUCKET it goes in.
- Weak source if: the unit is left implicit because the standard never names it in a heading. Standards that devote a section to this call it different things every time; the question is the same one.
### 05. Recognition and derecognition
- Belongs here: whether the item is on the books at all. Initial recognition trigger; derecognition criteria in the order they are applied; partial derecognition and continuing involvement; whether a change in terms replaces the item with a new one; recognition as an expense or transfer out on consumption or sale; the derecognition consequence of a write-off.
- Derecognition criteria keep their conditions word for word (for example "when, and only when", or a threshold such as "substantially all"). A test is never recorded without the condition that limits it.
- When the standard sets a test for one kind of item only, record which item it applies to and never extend it to others. If the standard gives no test for a question, record that it is silent rather than borrowing a test from elsewhere.
- Hand off: the amount -> Measurement. The category -> Classification and categorisation. What the item is -> Unit of account. Extinguishing an allowance rather than the item -> Impairment and write-downs. What follows in another section when a change in terms replaces the item with a new one (for example a new start date for a later test) -> the section that owns that consequence.
- Boundary: extinguishing the ITEM is here; extinguishing the ALLOWANCE is impairment. On a modification, whether the item SURVIVES is here; what the new amount is belongs to Measurement.
- Weak source if: the derecognition tests are listed without their applied sequence. The order is part of the requirement.
### 06. Classification and categorisation
- Belongs here: where the standard sorts items into categories that drive later treatment. The classification tests and the order they are applied in; each resulting category and what it commits the entity to; designation options and whether they are irrevocable; reclassification — when permitted, when required, when prohibited, and from what date it takes effect.
- Whether a classification, designation or reclassification is required, permitted or prohibited is kept exactly as the standard states it ("shall", "may", "only if", "irrevocable"). A permitted designation is never recorded as a requirement, and a conditional test is never recorded without its condition.
- A category assigned to an item in an example or illustration is recorded as that example's outcome, naming the example, and never as a general classification rule.
- Hand off: the measurement consequence of a category -> Measurement. A regime with its own qualifying criteria and discontinuation rules -> Elections and special regimes. The policy character of a designation -> also recorded in Judgements.
- Not applicable for many standards, and for some it applies to only one party to the arrangement. Both are correct states; record which.
- Weak source if: a category is recorded without its downstream consequence, or a designation is recorded without whether it can be undone.
### 07. Measurement
- Belongs here: how an amount is computed. Initial measurement including transaction costs; subsequent measurement by category; every measurement basis the standard uses and its arithmetic — INCLUDING a recoverable, realisable or fair amount and the techniques used to reach it; discount rates and present value technique; unwinding, accretion and time-value mechanics, including on an item already written down; the amount following a modification; the amount allocated across units identified in Unit of account; where gains and losses are presented and whether they recycle.
- Where the standard assigns a different rate, basis or input to different kinds of item, each is recorded against its own item and never generalised to all. Permissions and limits on them are kept word for word ("or an approximation", "only if, and to the extent that").
- A presumption and its fallback are recorded together, exactly as stated ("there is a presumption that... in those rare cases... the entity shall use..."). A presumption is recorded as rebuttable only if the standard calls it rebuttable.
- Figures, formulas and calculations taken from an example or illustration are recorded as that example's arithmetic, naming the example, and not as the standard's measurement method. A formula is recorded as the standard's own only if the standard itself states it.
- Hand off: the decision to perform a test and what happens when it fails -> Impairment and write-downs. The basis for splitting across components -> Unit of account. A measurement basis defined by another standard -> that standard, linked and not restated.
- Boundary: an amount representing WHAT THE ITEM IS WORTH is here — recoverable amount, value in use, fair value less costs of disposal, net realisable value. An amount representing THE LOSS is impairment. Interest stays here regardless of impaired status.
- Weak source if: recoverable-amount machinery is filed as impairment merely because its purpose is a loss test.
### 08. Impairment and write-downs
- Belongs here: the decision to test an amount for loss in value, the comparison that test makes, and what follows. What triggers a test and how often; indicators that a test is required; the level at which the test applies; what is compared with what; staging or bucketing; deterioration criteria and rebuttable presumptions; recognition of the loss and its allocation; reversal criteria — permitted, required, or FORBIDDEN; simplified approaches and practical expedients; write-off as the terminal point of the allowance.
- The items to which the test applies are listed here in full, as the standard lists them. A partial list is not recorded as the whole.
- Triggers, thresholds and presumptions keep their exact strength and role as stated — whether the standard calls something a requirement, a presumption, an indicator, an example of an indicator, or the latest point at which a step must occur. A presumption is recorded with what it presumes, what rebuts it, and the evidence needed to rebut it.
- Simplifications, approximations and practical expedients are recorded with every condition under which they are permitted and any circumstance the standard says rules them out.
- An outcome reached in an example or illustration (a party recognising a loss, moving between stages or buckets, or rebutting a presumption) is recorded as that example's outcome, naming the example, and never as a trigger or rule.
- Hand off: computing the amount compared against -> Measurement. Interest on a written-down item -> Measurement. Input estimation methodology -> methodology/research. Client parameters and thresholds -> client working papers. Regulatory floors or add-ons -> supervisory/regulatory. Disclosure of the loss -> Presentation and disclosure.
- Boundary: this section holds the TRIGGER, the COMPARISON, the CONSEQUENCE and the REVERSAL, plus any amount representing THE LOSS ITSELF. Amounts representing what the item is worth belong to Measurement. How the loss amount itself is measured (for example how expected losses are estimated) belongs here, not in Measurement.
- Weak source if: a rebuttable presumption is recorded without what rebuts it, or the reversal position is left unstated. Some standards require reversal, others forbid it; silence is not neutral.
### 09. Elections and special regimes
- Belongs here: optional or conditional regimes sitting alongside the main requirements, each with its own qualifying criteria, mechanics and discontinuation rules. Irrevocable policy choices carrying their own machinery. Temporary reliefs that operate during normal running.
- A regime is kept together: its requirements and its application guidance are filed here as a whole, not split across the other sections it touches. Those sections link to it.
- An election is recorded as optional, exactly as the standard grants it ("may", "may choose", "may elect"), together with the level at which the choice is made (item by item, by class, or for all items) and whether it can be revoked. An election is never recorded as a requirement.
- Qualifying criteria and discontinuation conditions keep their wording in full ("only if", "shall discontinue when", "for as long as"). A regime is never recorded with some of its qualifying criteria but not all of them.
- Hand off: designations that only change a measurement category -> Classification and categorisation. A straight either/or choice with no machinery of its own -> the section that owns the mechanic, with the choice recorded in Judgements. Reliefs available only on first application -> Transition and effective date.
- Boundary: a regime needs all three of qualifying criteria, mechanics, and discontinuation. Missing any one and it is a policy choice, not a regime.
- Weak source if: a regime is captured with how to qualify and how to apply but not when it must stop. Discontinuation is the part most often omitted and the part most often breached.
### 10. Presentation and disclosure
- Belongs here: what appears on the face of the primary statements and what must be told to the reader. Presentation requirements; disclosure requirements whether in this standard or its disclosure partner; where disclosure sits in a separate standard, the link and an explicit statement of how the split runs; disclosure attached to a specific election or regime; disclosure of judgements made.
- Each disclosure keeps its strength as stated: required ("shall disclose"), encouraged or permitted ("is encouraged to", "may"), or required only when a condition is met ("if material", "when the entity has elected"). A disclosure objective is recorded as an objective and is not turned into a list of specific required items, and specific items are not merged into the objective.
- Where the information must appear is recorded exactly as stated — on the face of a primary statement, in the notes, or either — and is not assumed.
- A table, format or wording shown in an example or illustration is recorded as that example's presentation, naming the example, and not as a required format.
- Hand off: the full text of a partner disclosure standard -> that standard's own map. Disclosure required only on first application -> Transition and effective date.
- Weak source if: disclosure is treated as belonging to this standard when it actually lives in a partner standard, or the split between the two is left implicit. Say where disclosure lives in the first line.
### 11. Judgements, estimates and policy choices
- Belongs here: every point at which the standard hands the entity a decision. Each judgement with its reference; each estimate and what it is an estimate of; each policy choice, whether irrevocable, and the level at which it is made; rebuttable presumptions with what rebuts them and the evidential bar; terms the standard leaves to the entity to define; unit-of-account determinations that require judgement; elections recorded alongside their owning section.
- This section is ADDITIVE, not exclusive. A judgement-creating requirement lives in its subject section AND is recorded here. It is the only sanctioned duplication.
- The duplication is by link, not by rewording: each item recorded here is one short line naming the decision point, with its clause reference and a link to the subject section that holds the full text. The full text is never restated here. This section is written after the other sections.
- A presumption is recorded here only if the standard itself calls it a presumption, and as rebuttable only if the standard says it can be rebutted. A statement is not promoted to a presumption, and a presumption is not promoted to a rebuttable one.
- A judgement is recorded as the decision the standard leaves to the entity, not as the answer an example reached. An example's conclusion is that example's outcome, named as such.
- Hand off: the answer for any given client -> client working papers. The estimation methodology -> methodology/research. The mechanics of an election -> the section that owns it.
- Test: could two entities applying this standard CORRECTLY reach different answers here? If yes, it belongs here whatever else it also belongs to.
- Weak source if: a presumption recorded anywhere else in the map does not also appear here. This is the section a working paper is written against, and a gap here is a gap in the watchdog.
### 12. Transition and effective date
- Belongs here: how an entity gets from the previous requirement to this one, and only that. Effective date and early application conditions; transition approach — full retrospective, modified retrospective, prospective; reliefs and practical expedients available on transition, with expiry; comparative restatement requirements; transition-specific disclosure; transition provisions attached to EACH amendment, recorded separately; withdrawal of superseded pronouncements.
- Each transition claim records the amendment or version it belongs to, so provisions from different amendments can never be merged into one.
- Reliefs and transition requirements keep their strength and limits as stated — required ("shall"), permitted ("may", "is not required to"), conditional ("if ... would require undue cost or effort") — together with when they apply and when they stop.
- A transition rule whose effect continues after first application (for example, applying until an item is derecognised) is recorded with how long it lasts and linked from the section whose requirement it changes.
- Hand off: steady-state requirements -> the functional sections. Reliefs that operate during normal running rather than only at first application -> Elections and special regimes. The bare dates -> also in Overview and status.
- Weak source if: transition provisions from several amendments are merged into one account. They are layered and each amendment carries its own; merging them is the commonest defect in this section.
### 13. Board reasoning
- Belongs here: why the requirements are as they are, keyed to the requirement each passage explains. Alternatives the issuer considered and rejected, with the reason. Concerns raised in consultation and how they were addressed. Dissenting opinions. Effects analysis where published. Reasoning carried forward from a predecessor standard without reconsideration, flagged as such. Comparisons with another framework's equivalent standard where the issuer publishes one.
- NOTHING IN THIS SECTION IS AUTHORITATIVE. It is not a requirement and must never be filed as one.
- Every claim here is worded as the issuer's reasoning, with the issuer as the subject ("The <issuer> considered...", "The <issuer> concluded..."), never as an obligation on the entity.
- A reference to reasoning is not reasoning. Pointers such as "see Basis for Conclusions paragraphs ..." are recorded on the requirement they sit beside, not as claims here. Claims here come only from the reasoning text itself.
- A dissenting opinion is attributed to the member who holds it and is never presented as the issuer's view.
- Hand off: anything readable as a requirement -> the functional section that owns it. Worked fact patterns -> Worked examples and illustrations.
- Boundary: if it argues, it is here. If it works through a fact pattern, it is examples.
- Value: when a working paper appears to conflict with a requirement, this is what settles whether the conflict is real or a misreading. Keep it even though it binds nothing.
- Weak source if: an entry carries the reasoning reference but not the requirement reference it explains. Both are needed or it cannot be found when it matters.
- Not applicable until a source containing the issuer's reasoning (such as a basis for conclusions) has been ingested. Until then the page says it is empty. Text from the standard itself, including its application guidance, is never reworded as the issuer's reasoning.
### 14. Worked examples and illustrations
- Belongs here: the issuer's own examples, each indexed to the requirement it illustrates, with the arithmetic where quantitative. Implementation guidance in question-and-answer form. An example is a passage the issuer labels as one (such as "Example 1" or "Instrument A"); a paragraph that only says "for example" is not.
- Each example is headed by the issuer's own example number and title (for example "Example 1 – <title>"), not by the paragraph number it starts at. Its paragraph numbers are given in the citations.
- Every example claim names its example and keeps the parties and facts exactly as given ("In Example 4, Entity A ..."). It is never restated as a general statement about entities.
- The facts and assumptions an example relies on are recorded with its outcome, including any simplifications the example states (for example "for simplicity, it is assumed that ..."). An outcome is never recorded without the facts that produced it.
- Each example claim carries the authority status read from the authority sentence. Example claims are filed only here; the section that owns the requirement links to the example rather than holding a copy of it.
- AUTHORITY IS NOT ASSUMED. Read it from the standard's own authority sentence, transcribed in Overview and status. Most issuers place examples OUTSIDE the binding scope; some place them inside, in which case they bind. Getting this wrong in either direction is a correctness failure, not a tidiness one.
- Hand off: examples the firm or a third party constructed -> technical guidance, never here. Argument about why a rule exists -> Board reasoning.
- Application guidance in the standard's own appendices is not an example, even where it says "for example". It stays in the section that owns the requirement and is never copied here.
- Not applicable where the issuer publishes no examples with the standard, which is common outside the largest standards. The other sections then correctly carry no example references, and that is complete rather than missing.
- Weak source if: an example is captured without the requirement it illustrates, or its authority is asserted rather than read from the authority sentence.
### 15. Interactions and application in practice
- Belongs here: relationships. Standards this one touches and the nature of each — scope boundary, disclosure partner, measurement input, consequential amendment. Standards this one interprets, where it is an interpretation. Interpretations and agenda decisions issued on this standard, indexed. Comparisons with another framework's equivalent. Pointers out to client working papers, methodology/research, supervisory/regulatory and technical guidance.
- Agenda decisions belong in this store, not in technical guidance. They are issuer output and entities are expected to apply them, but they are not part of the standard. Index them here and record each against the section whose subject it affects.
- An agenda decision or interpretation is worded with its issuing body as the subject ("The <issuing body> concluded that ..."), with its date and the question it answered, and carries statement kind editorial. It is never worded as a requirement of the standard.
- An agenda decision reproduced inside another source (for example, printed as a note in an annotated edition) is recorded once, here, under its own identity. The section it bears on links to it rather than holding a copy, and repeat printings are not recorded again.
- A requirement of another standard is attributed to that standard by name and is not recorded as a requirement of this one.
- Hand off: whether the standard applies at all -> Scope and applicability. The content of anything linked -> its own store.
- Boundary: scope decides whether; this section describes how, once both apply.
- Weak source if: a link names a standard but not the specific part of it, or an agenda decision is indexed here without being recorded against the section it actually bears on.

## Slugs and links
- Slugs are lowercase kebab-case, unique and stable. The top-level page's slug is overview. A section slug is the framework slug plus the slugified section name (e.g. ifrs-9-impairment-and-write-downs). They come from the fixed vocabulary, so they are never renamed and never invented.
- Each composed page type has a fixed slug pattern built from its controlled list, never from free text: source-<source-name>, <framework>-entity-<designation>, <framework>-concept-<term>, <framework>-comparison-<subject-a>-vs-<subject-b>, <framework>-synthesis-<question-id>. Two pages that would produce the same slug are the same page.
- Link with [[slug]], and only to a page that exists or is in the fixed vocabulary. Anything else is written as plain text, as set out in Writing page text.
- The index body's [[slug]] entries are the only admissible navigation targets — fifteen of them. A page missing from the index is a page the librarian cannot choose, even if it exists.
- Composed pages are not navigation targets for the librarian. They are reached through links from topic pages and from the overview's lists, and are never used to choose where a claim is filed.
- Composed pages refer to claims by clause reference (and claim ID where the engine stores claims), not by copying the claim's text. A reference to a claim that has been discarded or superseded renders as a dead reference, so a stale citation is visible.
- Display text is written [[slug|display text]]. The part before the pipe is the page slug; the part after is what the reader sees. Citations use this form to show the clause: [[source-<source-name>|<clause reference>]].

## Page content
- A section body is rebuilt from the rendered claims filed to it and never hand-edited. The rebuild clears as well as writes, so a section whose claims have gone says so rather than keeping what it last said.
- Every statement shows its clause reference, and every statement from application guidance, an example, an editorial note or the basis for conclusions says what it is in its wording, as set out in Writing page text, so its authority is visible wherever it appears.
- pages.summary is derived — the first three rendered claims, on one line. pages.description is generated from the page's claims (what the page covers, as opposed to a fact from it), written in the same statement as description_grounding — the top-15 term counts and the statement-kind split it was built from — so the two cannot disagree. Where a page holds requirement claims, the summary is drawn from those first, so a page is never summarised by an example or an annotation.
- Claims are tagged by statement kind, read from the clause the quote sits in rather than from the file it came from: requirement, application guidance, example or editorial. A question about what the standard requires is answered only from requirement claims, so it can never be answered with an illustration or an annotation.
- Verification compares each claim with its quote. It checks that the claim is supported, and that the claim keeps the quote's force (required, permitted, expected, typically) and its named parties. A claim that fails is rewritten once from its quote; if it fails again, the quote itself becomes the claim. Unsupported claims are kept for audit and never rendered; a claim is rendered only once it is fully supported.
- Composed pages are rebuilt the same way: from the claims they cite, cleared as well as written, and flagged when a cited claim changes or is withdrawn.

## Contradictions and updates
- A contradiction is recorded as a row with both positions and the authority that favours one, and both sides are surfaced at query time rather than one being silently preferred.
- Before a contradiction is recorded, the two claims are compared through their quotes. If the quotes agree and only the claims' wording differs, it is a rewriting error: the claims are regenerated from their quotes and no contradiction is recorded.
- Where two claims of different statement kind conflict, the authority that favours one follows the kind: a requirement outranks application guidance, which outranks an example or an editorial annotation. Both positions are still surfaced, with the ranking stated.
- A recorded contradiction is shown on every page holding either claim, as: > [!warning] Contradiction: <source A> says X; <source B> says Y. — with the ranking by statement kind where one applies.
- Supersession is explicit: replaced_by_source_id and effective_to date the old claim rather than deleting it. Each claim records the amendment or version it comes from, so a claim from a later amendment supersedes the earlier one explicitly rather than appearing as a contradiction.
- When a claim is superseded, the page shows the current claim with a note beneath it: > [!note] Updated: <new source/amendment>, effective <date>, replaces <old source>. Changed: <what changed>. Reason: <the amendment or source that changed it>. The superseded claim is kept, dated, and not edited in place.
- Cross-store findings are dispositioned through a review step with a named actor, never by editing a claim in place.
- Nothing is deleted to resolve a disagreement. The old assertion stays, dated, so the record shows what changed and when.

## Style
- Plain, precise language. No filler. Short paragraphs and lists.
- A claim is one verifiable statement with a verbatim quote. Never invent or infer beyond the text.
- A claim keeps the subject and the force of its quote. A named party stays named and is never turned into "an entity" or "you"; shall/must, may/can, should and generally/typically are carried over unchanged; conditions such as "only if", "unless" and "except" are kept; a presumption is not made rebuttable unless the quote says so.
- Claims from application guidance, examples, editorial notes or the basis for conclusions say what they are in their wording: "Application guidance states ...", "In Example <n>, <party> ...", "The editorial note states ...", "The <issuer> concluded ...", "The <issuing body> concluded ...". Claims from the Standard's own paragraphs carry no such wording, whatever their force.
- A claim states content. A heading, a table fragment, or a sentence that only points elsewhere ("Paragraph X governs Y", "Section Z contains the requirements") is not a claim.
- Be exhaustive within a section — if it supports ten claims, return ten — but a section that genuinely states little should return little. Exhaustive means every point once: the same point from the same clause is not recorded twice.
- An honest empty answer must stay expressible. Zero pages, and zero claims on a page, are answers; the schema never forces a claim where the source states none.

## Writing page text
These rules apply every time the maintainer writes or rewrites page text, whether or not the engine stores separate claims.
- Cite the clause on every sentence that states something from a source. End each such sentence with [[source-<source-name>|<clause reference>]]. A citation to the whole document with no clause reference is not allowed. A sentence drawn from two clauses cites both.
- Sentences about the wiki itself (what a section covers, whether it holds requirements, what the overview lists) describe the wiki, not a source, and carry no source citation. A page number or the start of a source is never cited for them. A line that applies to every section is written once, not repeated under each.
- Use the source's own force words. shall, must, may, can, should, might, for example, typically and generally are copied exactly as the source uses them. "May be considered" never becomes "is", and "might, for example" never becomes "often".
- Write up what each source paragraph actually says: its definitions, numbers, thresholds, time periods, conditions, exceptions and who must do what. A mention or a citation alone is not a write-up.
- Keep every condition, word for word. "Only if", "unless", "except", "subject to <clause>", "regardless of", thresholds, time limits and similar limits stay in the sentence they limit. A condition is never dropped, shortened or moved away from what it limits, and a list of conditions keeps every item with the source's own lettering ((a), (b), (i), (ii)).
- Say what kind of paragraph a sentence comes from. A sentence from application guidance opens "Application guidance states ..."; from an example, "In Example <n>, ..."; from an editorial note, "The editorial note states ..."; from the basis for conclusions, "The <issuer> concluded ...". A sentence from the Standard's own paragraphs has no opener, whatever its force: a requirement ("shall"), a permission ("may"), an objective or a presumption is written without one. The opener is chosen by where the paragraph comes from, never by its force. A short linking word may come before the opener (for example "However, application guidance states ...").
- Quote where the wording matters. Where a short phrase carries the meaning (a defined term, a threshold, a presumption), put it in quotation marks exactly as the source writes it.
- Say each point once. A point is written once, on the page whose section brief covers it, and only once on that page: a clause already written up is not restated in a summary, a list or a later sub-heading. A sentence drawn from several clauses cites them all instead of being repeated for each. Other pages link to that page rather than restating the point.
- Stay inside the section. A page holds only what its section brief covers. Content that belongs to another section is written there, not here.
- Link only to pages that exist. Other standards and documents are written as plain text, by designation only and always in the same form, unless a page for them exists.
- Never state facts about the wiki from memory. Dates come from the log or the source record; counts are counted from the pages, not estimated. If a figure is not known, it is left out.
- One overview page, slug overview. No second top-level page is created under the framework slug or any other name.
- Each section is broken into sub-headings by subject (for example “Loss allowance”, “Significant increase in credit risk”, “Measurement”), so no block of text runs for more than a few hundred words. Sub-headings follow the standard’s own headings where it has them. Sub-headings are by subject, never one heading per paragraph number.

## Workflow: Ingest
- Register the source before anything is extracted: issuer, designation, edition, part, and a content hash. The source page is created only if the designation resolves. A source whose hash matches one already ingested is not ingested again; a new hash for the same designation is a new version, and its claims supersede the old ones under Contradictions and updates rather than being added beside them.
- Read the authority sentence first and record it in Overview and status. Then assign every part of the source a tier: binding text, application guidance, examples and illustrations, reasoning, or editorial material. The tier of the part a quote comes from sets the claim's statement kind.
- Separate editorial material from the standard's text before any claim is drawn: bracketed notes, cross-reference boxes, footnoted annotations and reproduced agenda decisions. They are quoted only as editorial claims, never as part of the clause they sit beside.
- Split the text into clauses using the source's own labels, and give every claim one clause reference in a fixed form: numbered paragraphs exactly as the source prints them, including sub-paragraph letters; application guidance, examples and reasoning by their own printed labels; defined terms as AppA:<term> (or the glossary's own name where it has one); editorial notes as ED:<clause they sit beside>; agenda decisions and interpretations as AD:<issuer>-<date>. A quote that crosses two clauses becomes two claims.
- Tables: a table that states requirements, definitions or required disclosures is claimed row by row, each claim carrying the table's reference and its column headings. A table of figures inside an example stays with that example. Layout fragments, headings and running heads are discarded.
- Extract claims against the section briefs. Every claim carries its quote, character offsets, clause reference, statement kind, subject, force (required, permitted, expected, typically, illustration) and the amendment or version it comes from.
- Verify every claim as set out in Page content, then file it to the section its brief routes it to. A claim that names no section of the fifteen is discarded and counted.
- Route application guidance with the requirement it applies. A B paragraph goes to the section that holds the chapter its number points to (B5.5.x with chapter 5.5, B6.x with chapter 6), unless a section brief hands it off. Application guidance that says "for example" is still application guidance, not an example: it goes to the section that owns its requirement, not to the examples section.
- Check coverage: every clause of binding text has at least one claim, or is recorded as stating nothing that can be claimed. Gaps are listed, never filled by inference.
- Rebuild the affected pages, then run the checks in Workflow: Maintain. An ingest that fails those checks is not exported.

## Workflow: Answer and check
- Choose where to look from the overview only, then read the claims on the sections chosen. A question about what the standard requires is answered from requirement claims; any other kind used in the answer is labelled as what it is.
- Every statement in an answer rests on a claim and cites its clause reference (and claim ID where the engine stores claims). Citing a whole document or page is not a citation. Nothing is stated that no claim supports.
- An answer keeps each claim's force, subject and conditions. A permitted step is not presented as required, an example's outcome is not presented as a rule, and a condition is not dropped to shorten the answer.
- Before saying the standard does not address something, search every section, including Definitions, for the terms involved. Only then say it is not addressed, and say what was searched for.
- Answers are laid out as: the answer; the clause references relied on; anything the standard does not address; and, kept separate, any non-authoritative material (examples, reasoning, editorial notes, agenda decisions) with its kind stated.
- Checking a client statement (the watchdog): find the clause or clauses the statement relies on, compare the statement with their claims and quotes, and give one verdict — consistent; stricter than the standard; looser than the standard; contradicts the standard; not addressed by the standard; or relies on non-authoritative material only. Every verdict cites the clause and quotes the passage it rests on.
- A client document never changes a claim in this store. Findings that bear on the store go through the review step in Contradictions and updates.
- An answer worth keeping is filed as a synthesis page under the rules in Page types.

## Workflow: Maintain
- After every ingest, and before export, run these checks. All must pass:
  1. every claim has a clause reference and a quote that is found at its offsets in the source;
  2. no claim from an editorial, example or reasoning part carries statement kind requirement;
  3. no claim is a heading, a table fragment or a pointer only;
  4. no two claims share a clause and overlapping offsets;
  5. no unsupported claim is rendered;
  6. every claim that failed the force or named-party check was rewritten or replaced by its quote;
  7. every binding clause has a claim or is recorded as stating nothing claimable.
- An ingest that fails is not exported. The failures are reported by check and by section, fixed, and the checks run again.
- After a page is written, it is checked against its source paragraphs: every lettered or numbered part of each paragraph appears, and every sentence from application guidance, an example, an editorial note or the basis for conclusions carries its opener. A page that fails is sent back once with the list of failures and rewritten.
- Each ingest reports, outside this schema: claims by statement kind and by section, verification results, claims replaced by their quote, claims discarded by reason, and coverage gaps.
- Synthesis and comparison pages whose cited claims have changed are rebuilt or flagged stale. Contradictions and supersessions are handled as set out in Contradictions and updates.

## Checks
The engine reads these lists to route the issuer's labelled examples and, after a page is written, to check it as set out in Workflow: Maintain. It reads the words only from here: a list that is missing switches off what uses it.
- Paragraph kinds (as the PDF reader names them): appendix_b = application guidance; example = example; basis_for_conclusions = basis for conclusions; note = editorial note
- Openers: application guidance = "Application guidance states"; example = "In Example <n>,"; editorial note = "The editorial note states"; basis for conclusions = "The <issuer> concluded", "The <issuer> considered"
- Linking words allowed before an opener: "However,", "In addition,", "For example,", "Alternatively,", "Similarly,", "Furthermore,"
- Lettered part forms: "(a)", "(i)"
- Condition phrases: "only if", "unless", "except", "subject to", "regardless of"
- Authority forms: "is set out in paragraphs ... and ...", "This appendix is an integral part of the Standard"
- Source-page parts: what the document is = issuer, edition, part; authority sentence = authority forms; sections it informs = informed sections; key takeaways as linked claims = cited claims
- Key takeaways: at most 5
- Examples section: 14
- Example labels (an issuer's own example, routed to the examples section): "Example <n>", "Instrument <n>", "Scenario <n>", "Illustration <n>"
