# Client wiki schema
Schema version client-1.17 (built from schema 3.12)
This document tells the wiki maintainer (the LLM) how a client wiki is structured. It is written for any client's papers on any standard. Nothing in it names a particular client.

## Purpose
A persistent, interlinked knowledge base compiled from one client's papers: policies, methodologies, model documentation, calculation procedures, validation reports and similar documents. Pages are written and maintained by the engine; humans curate sources and ask questions. No page body is hand-written.
The wiki records what the client's papers say the client does, and nothing else. It never states what the standard requires, never fills a gap from the standard or from general practice, and never judges whether the client complies. A sentence in a client paper that quotes or cites the standard is recorded as the client citing it, never as the client's own method and never as the standard's requirement.
The wiki uses the same fifteen sections, with the same numbers and names, as the standard's wiki. A section here can therefore be read against the same section there. Sections the client's papers do not address are created and say they are empty; an empty section is an answer, not a fault.
Each claim is a concise statement of what its source says, linked by character offsets to the passage it rests on, so it can always be traced back to the original wording. A claim may be shorter than its source but never changes its meaning: it keeps who does what, and whether the paper states it as a decision, a method, a result, an assumption or an open item. Where the two differ, the source wording governs.
Every sentence on every page that states something from a source ends with the place it comes from, written [[source-<source-name>|<location>]], on every page without exception. Sentences about the wiki itself are the only exception, as set out in Writing page text.
Four further rules apply on every page without exception. A sentence from a result, an open item, a cited standard, an illustration or an editorial note opens with what it is, as set out in Writing page text; a sentence from the paper's own policy or method text has no opener. Every source passage is written up in full: its numbers, thresholds, time periods, conditions, exceptions, parameters and formulas are stated, and a list keeps every item with the source's own lettering or numbering. All fifteen section pages are created on every ingest, including those that end up empty. A link points only to a page that exists; other documents are written as plain text.

## Page types
There are eight page types, and the vocabulary is fixed rather than minted per document, so the same structure exists for every client and nothing drifts between ingests. Every page is created from a controlled list or a saved question, never from free text or from whatever a source happened to say.
Only topic and subtopic pages hold claims. Every other page type is composed: it holds no claims of its own and is built from links to claims already filed, so nothing is stated twice in different words.
- overview — the single top-level page, slug overview. Lists the fifteen sections, each with one line saying what the section covers, followed by a link to its page if the page holds claims, or the word "Empty" if it holds none. The overview holds no claims: it carries no source citations, states no fact from a source, and gives no view on how fully a section is covered. The overview and the page list (each page's title and one-line summary) are where the librarian starts when choosing where to look. No second top-level page is created.
- source — one per registered client paper, slug source-<name>. States what the document is (client, title, version, date, status such as draft or approved, owner), its stated purpose and scope transcribed verbatim where the paper states them, and which sections it informs. These facts are written plainly, without an opener, and cited to where the paper states them. A fact the paper does not state but the engine supplies from the upload (issuer, edition, part, status) is written with "(as entered on upload)" and carries no source citation; it is never cited to "Cover" or any other location; text printed before the paper's first heading (a cover or title page) is cited as "Cover". Each of client, title, version, date, status and owner that neither the paper states nor the engine supplies is written as "Not stated", with no citation, and is never guessed. A paper marked as a draft or work in progress, by the paper or by the engine, says so in its first line. Key takeaways are at most five of the source's own highest-ranked claims, linked, not a written summary. The source page holds only these parts.
- entity — a specific, named thing the client's papers refer to: a model, a system, a data source, a portfolio or legal entity, a committee or function, a regulator, a standard or another document. Lists every claim that names it and the nature of the link (input, output, owner, approver, scope). Created only from names that appear in the papers.
- concept — a term, rule or method the client's papers use: a term the client defines, a named method (for example a named estimation technique), or a named threshold or rule. States whether the client defines it, takes it from another document, or uses it without defining it, links to its definition in Definitions rather than copying it, and links to every claim that uses it.
- topic — one of the fifteen fixed sections. Created from the vocabulary before any claim is written, so an empty section is a page that says it is empty, not a missing page. An empty section page holds only the word "Empty.", with no explanation, as Checks sets out. A claim that names a section outside the fifteen is discarded and counted.
- subtopic — part of one section, used where a section is split, as Checks sets out. It holds claims and follows every rule a topic page follows. It is reached from its section page, which becomes an index: one line per item, saying what it covers and which locations it cites, grouped by subtopic page, with no full write-ups.
- comparison — a side-by-side view of two or more things from the client's papers (for example two portfolios' methods, or two versions of one method). Each row links to the claims it rests on.
- synthesis — an analysis or answer filed back from a query. Records the question and date, and is never used as a source for new claims.

## The fifteen sections
Each brief states what belongs on the page, what to hand off and where, the boundary against the section most likely to be confused with it, and what makes a weak source for it. The whole of each brief is sent to the extraction model, which is what routes a claim to a page. Every brief is about what the client's papers say the client does on that subject.
Every claim carries its statement kind — policy or method, result, open item, cited standard, illustration or editorial — read from the passage its quote sits in.
### 01. Overview and status
- Belongs here: what the client's set of papers is and where it stands — each paper's purpose and scope as stated, version history, dates, status (draft, work in progress, approved), owners and approvers, what each paper replaces, and how the papers relate to one another (which paper feeds which).
- Status is recorded exactly as the paper states it. A draft is never described as approved, and a paper with no stated status is recorded as having none.
- Hand off: changes to a method over time -> Transition and effective date. Governance of updates and validation -> Judgements, estimates and policy choices, and Interactions and application in practice.
- Not the overview page: this is a topic section holding claims; the overview page is the index of the fifteen and holds none.
- Weak source if: a paper's version or status is left out, or the relationship between papers is assumed rather than stated.
### 02. Scope and applicability
- Belongs here: what the client's papers apply to. Entities, portfolios, products, segments and exposures covered; those excluded, with any stated reason; thresholds that bring items in or out; the period the papers cover.
- Exclusions and their exceptions keep their conditions word for word ("except", "unless", "other than").
- Hand off: how items are grouped once in scope -> Unit of account. Treatment of anything in scope -> the section that owns it.
- Boundary: scope decides WHETHER a paper applies; unit of account decides HOW items are grouped.
- Weak source if: an exclusion is recorded without what happens to the excluded items, or a list of portfolios is recorded incompletely.
### 03. Definitions
- Belongs here: every term the client's papers define, verbatim with its location, including definitions of default, cure, write-off, credit-impaired, past due and similar operational terms; terms used but not defined, recorded as undefined; and terms the client takes from another document, recorded with that document named.
- Where two client papers define the same term differently, both are recorded and the difference is noted.
- Each defined term creates or updates its concept page, which links back to the definition here.
- Definitions holds terms only. A formula, method, parameter or reference to literature is not a definition: it is written on the page of the method it belongs to, and the term's line here links to that page.
- Hand off: thresholds applied using a defined term -> the section that applies them. Formulas and the meaning of their symbols -> the section that holds the method.
- Weak source if: a term is used throughout the papers without recording whether the client defines it.
### 04. Unit of account
- Belongs here: the level at which the client applies its methods — segmentation, portfolios, pools, rating grades, groupings for collective assessment, the basis for grouping, individual versus collective assessment, and when an item moves between groups.
- Segmentation criteria and any tests used to support them are recorded with their results as stated.
- Hand off: whether a paper applies at all -> Scope and applicability. The category an item falls into -> Classification and categorisation. Amounts computed for each group -> Measurement or Impairment and write-downs.
- Boundary: this section asks HOW ITEMS ARE GROUPED. Classification asks WHICH CATEGORY they are in.
- Weak source if: segments are listed without the criteria that define them.
### 05. Recognition and derecognition
- Belongs here: when the client records an item and when it removes it. Initial recognition; derecognition; modifications and whether a modification is treated as a new item; write-off policy and its triggers; recoveries after write-off.
- Triggers keep their conditions and thresholds word for word.
- Hand off: amounts -> Measurement. The allowance on an item -> Impairment and write-downs.
- Boundary: removing the ITEM is here; adjusting the ALLOWANCE is impairment.
- Weak source if: a write-off or modification policy is recorded without its trigger.
### 06. Classification and categorisation
- Belongs here: how the client sorts items into categories that drive later treatment. Business model assessments; contractual cash flow assessments; categories assigned to portfolios; designations and elections of category; reclassification policy.
- A category assigned to a portfolio is recorded against that portfolio and never generalised.
- Hand off: the measurement that follows from a category -> Measurement. The risk grade or stage of an item -> Impairment and write-downs.
- Weak source if: a category is recorded without the assessment that produced it.
### 07. Measurement
- Belongs here: how the client computes amounts other than the loss allowance. Effective interest rate; amortised cost; fair value and the techniques used; discount rates and present value mechanics; exposure and balance calculations used across the papers; reconciliations of balances.
- Formulas are recorded exactly as the paper states them, with every term defined as the paper defines it.
- Hand off: the loss allowance and its inputs -> Impairment and write-downs.
- Boundary: an amount representing WHAT THE ITEM IS WORTH or OWES is here. An amount representing THE LOSS is impairment. How an exposure amount is calculated from balances is here; how exposure is projected to default (credit conversion factors, prepayment) is Impairment and write-downs.
- Weak source if: a formula is recorded without its terms.
### 08. Impairment and write-downs
- Belongs here: everything the client does to estimate and recognise credit losses. Staging and its criteria; significant increase in credit risk and its thresholds; rating and scoring models used for staging or for loss estimation; probability of default, including term structures, transition matrices, calibration and point-in-time adjustment; loss given default, including recoveries, collateral and cure; exposure at default, including credit conversion factors and prepayment; forward-looking information, scenarios and their weights; the expected credit loss calculation by portfolio and product; overlays and adjustments; lifetime and twelve-month horizons; simplified approaches.
- Model inputs, model outputs and model-building steps (data selection, variable selection, statistical tests and their results) are all recorded here, against the parameter they serve. The paper's own headings set the sub-headings.
- Thresholds, horizons, weights and parameters keep their exact values and units as stated. A result is recorded as a result of the paper that reports it, with its date or period where stated, and never as a fixed rule.
- Hand off: amounts other than the loss -> Measurement. Write-off of the item -> Recognition and derecognition. Disclosure of the loss -> Presentation and disclosure.
- Weak source if: a threshold, weight or parameter is recorded without its value, or a model is recorded without what it is used for.
### 09. Elections and special regimes
- Belongs here: optional regimes and reliefs the client says it applies, each with its qualifying criteria, mechanics and when it stops — for example hedge accounting, practical expedients, simplified approaches taken as a policy, and exemptions the client relies on.
- An election is recorded as the client's choice, with the level at which it is made and whether it can be changed, exactly as the paper states it.
- Hand off: a choice with no machinery of its own -> the section that owns the mechanic, recorded also in Judgements.
- Weak source if: a regime is recorded with how it is applied but not when it stops.
### 10. Presentation and disclosure
- Belongs here: what the client reports and discloses. Reporting outputs; disclosure tables and their contents; reconciliations and movement analyses produced; where each item is reported.
- A table format shown in a paper is recorded as that paper's format, not as a requirement.
- Hand off: the calculation behind a disclosed figure -> the section that computes it.
- Weak source if: a disclosure is recorded without where it is reported.
### 11. Judgements, estimates and policy choices
- Belongs here: every point at which the client's papers record a decision, assumption, expert judgement, management overlay, proxy or simplification. Each with its location and a link to the section that holds its full text.
- When this section grows past the page size limit it is split by the section each line points to, as Checks sets out.
- This section is ADDITIVE, not exclusive. A judgement lives in its subject section AND is recorded here by link: one short line naming the decision point, ending with the source citation of the passage it rests on ([[source-<source-name>|<location>]]) and then a link to the subject section. A link to a wiki page is not a citation; every line carries both. The full text is never restated here. This section is written after the other sections.
- Test: could another entity reasonably have chosen differently here? If yes, it belongs here.
- Weak source if: an assumption recorded anywhere else in the wiki does not also appear here.
### 12. Transition and effective date
- Belongs here: how the client's methods change over time. Recalibrations and redevelopments; version changes and what changed; the date from which a method applies; parallel runs; planned changes to a method as a whole (a redevelopment, a new version).
- An open item about a particular method, parameter or data step (work to be completed, a value to be confirmed) is written on the page of the method it concerns, not here.
- Each change is recorded with the version or date it belongs to, so changes from different versions are never merged.
- Hand off: the current method -> the section that owns it.
- Weak source if: changes from several versions are merged into one account.
### 13. Board reasoning
- Belongs here: why the client chose its approach, keyed to the method each passage explains. Alternatives considered and rejected, with the reason; limitations acknowledged; rationale for thresholds, weights and model choices; responses to findings from validation, audit or regulators.
- Every claim here is worded as the client's reasoning, with the paper as the subject ("The <document> explains that ..."), never as a method in its own right.
- Hand off: the method itself -> the section that owns it. Worked calculations -> Worked examples and illustrations.
- Boundary: if it argues why, it is here. If it works through numbers, it is examples.
- Weak source if: a reason is recorded without the method it explains.
### 14. Worked examples and illustrations
- Belongs here: the client's own illustrations and worked calculations, each indexed to the method it illustrates, with the arithmetic as shown.
- This section is split by the section each illustration illustrates, as Checks sets out. Its own page is the index of those subtopic pages.
- Each illustration is named by its own label or title, never by its location alone.
- Every illustration claim names its illustration and keeps its facts and figures exactly as given. It is never restated as a general method.
- Weak source if: an illustration is recorded without the method it illustrates.
### 15. Interactions and application in practice
- Belongs here: relationships. Standards, regulations and supervisory guidance the papers name, with the part named; other models, systems and papers that feed into or draw from each method; governance, ownership, approval, monitoring and validation arrangements; dependencies on third-party data or tools.
- A requirement of a standard or regulation that a paper quotes or restates is recorded as the paper citing it, with the paper as the subject, never as the client's method. A method that only names a standard or approach it follows (for example "aligned with <approach>") is method text, written once as method; the standard or approach named is recorded as an entity.
- Where the passage that names a standard, regulation, model, data source or document is written up on another section's page, it is recorded here by link, not restated: one short line naming the relationship, ending with the source citation of the passage it rests on and then a link to the page that holds the full text (a link to a wiki page is not a citation; every line carries both), as in Judgements, estimates and policy choices. Only relationships written up nowhere else (for example a list of input files and their owners) are written in full here.
- A reference to academic or other literature is written with the method it supports, on that method's page, and is not listed here or in Definitions. A paper's reference list is never written up as a list on any page.
- Hand off: whether a paper applies at all -> Scope and applicability. The content of a linked paper -> its own source.
- Weak source if: a dependency names another model or document but not what passes between them.

## Slugs and links
- Slugs are lowercase kebab-case, unique and stable. The top-level page's slug is overview. A section slug is the two-digit section number and the slugified section name (e.g. 08-impairment-and-write-downs).
- Each composed page type has a fixed slug pattern: source-<source-name>, <client>-entity-<name>, <client>-concept-<term>, <client>-comparison-<subject-a>-vs-<subject-b>, <client>-synthesis-<question-id>. A subtopic page's slug follows Checks. Two pages that would produce the same slug are the same page.
- Link with [[slug]], and only to a page that exists. Anything else is written as plain text.
- The overview links every section page. Subtopic pages are reached from their section's index page or from the page list.
- Composed pages may be read when answering, like any page on the page list, but are never used to choose where a claim is filed. Saved answers are not on the page list; they are read alongside, as Answer and check sets out.
- Display text is written [[slug|display text]]. Citations use this form to show the location: [[source-<source-name>|<location>]].

## Page content
- A section body is rebuilt from the rendered claims filed to it and never hand-edited. The rebuild clears as well as writes.
- Every statement shows its location, and every statement that is not the paper's own policy or method text says what it is in its wording, as set out in Writing page text.
- Claims are tagged by statement kind, read from the passage the quote sits in: policy or method, result, open item, cited standard, illustration or editorial.
- Verification compares each claim with its quote. It checks that the claim is supported, and that it keeps the quote's force, values and named parties. A claim that fails is rewritten once from its quote; if it fails again, the quote itself becomes the claim. Unsupported claims are kept for audit and never rendered.

## Contradictions and updates
- Where two client papers state different methods, values or definitions for the same thing, both are recorded as a contradiction row with both positions, the version and status of each paper, and both are shown at query time. Neither is silently preferred.
- Before a contradiction is recorded, the two claims are compared through their quotes. If the quotes agree and only the wording differs, the claims are regenerated and no contradiction is recorded.
- A recorded contradiction is shown on every page holding either claim, as: > [!warning] Contradiction: <source A> says X; <source B> says Y.
- A later version of the same paper supersedes the earlier one explicitly: the old claim is dated and kept, not deleted, and the page shows: > [!note] Updated: <new version>, replaces <old version>. Changed: <what changed>.
- Nothing is deleted to resolve a disagreement.

## Style
- Plain, precise language. No filler. Short paragraphs and lists.
- A claim is one verifiable statement with a verbatim quote. Never invent or infer beyond the text.
- A claim keeps the subject and the force of its quote. A named model, portfolio, committee or system stays named; shall/must, may/can, should, will, is to be, generally and typically are carried over unchanged; conditions are kept.
- A claim states content. A heading, a table fragment, or a sentence that only points elsewhere ("see section X") is not a claim.
- Be exhaustive within a section, but a section the papers say little about returns little. Exhaustive means every point once.
- An honest empty answer must stay expressible. Zero claims on a page is an answer.

## Writing page text
These rules apply every time the maintainer writes or rewrites page text.
- Cite the location on every sentence that states something from a source. End each such sentence with [[source-<source-name>|<location>]]. A location is the full heading path the passage sits under, from the top heading down, never a lower heading on its own, written as the paper prints it; where the paper prints heading numbers, the heading's own number and title are enough, because the number already places it (for example "4.2 Staging Methodology", or "ECL Parameters > Staging Methodology" where headings are not numbered); a table or figure adds its own label ("> Table 3"). Text printed before the first heading is cited as "Cover"; a document control or revision history table is cited as "Document control". A footnote is cited by the location of the passage that carries its marker, never as "Footnote <n>". A citation to the whole document with no location is not allowed. A sentence drawn from two locations cites both. A list, table or formula written directly under a cited introducing line takes that line's citation; the introducing line itself must carry the citation, and naming the location in words ("as printed under Appendix 1") is not a citation; so its items, rows and formula lines carry none of their own; the same applies to a list of a formula's terms ("where: ...") that follows the formula. An item drawn from a different location cites that location.
- Sentences about the wiki itself (what a section covers, whether it is empty, which sections a source informs) carry no source citation. A line that applies to every section is written once.
- Use the source's own force words, copied exactly. "Will be" never becomes "is", and "may" never becomes "shall".
- Write up what each passage actually says: its definitions, values, units, thresholds, time periods, conditions, exceptions, formulas and who does what. A mention or a citation alone is not a write-up.
- Keep every condition, word for word, in the sentence it limits. A list keeps every item with the source's own lettering or numbering, and a bulleted list keeps every bullet.
- Say what kind of passage a sentence comes from. A sentence from the paper's own policy or method text has no opener, whatever its force. A sentence reporting a result opens "The <document> reports ..."; an open item, planned work or limitation, "The <document> notes as outstanding ..."; a quoted or cited standard or regulation, "The <document> cites <designation> ..."; an illustration, "In <example label>, ..." (for example "In Illustration 2, ...") or, where it has no label, "In the illustration on <title>, ..."; an editorial note or footnote, "The editorial note states ..."; reasoning, "The <document> explains that ...". The opener is chosen by the kind of passage, never by its force.
- Formulas are written exactly as the paper states them, with each term's meaning as the paper gives it.
- A section page starts with its content. It does not restate its brief or describe what the section covers.
- A topic or subtopic page records what the paper states, not what it leaves out; it never says that something is not stated, not addressed or was searched for, as Checks sets out. "Not stated" is used only on the source page and in Overview and status, for the document facts listed there; elsewhere, something the paper does not state is simply not written.
- Tables are written in full, row by row, under an introducing line that names the table, its location and its column headings. This applies to every table that holds content — parameters, thresholds, weights, mappings and results alike. A table that is only layout, or repeats a table already written up, is not written again. A table of results opens with the result opener on its introducing line.
- A chart, screenshot or other image is recorded as existing, with its caption and location, on the page of the passage it sits in. It is not an illustration and is never routed to Worked examples and illustrations. Values are never read off an image. A line that only points to an image elsewhere ("Reference: <screenshot>") is a pointer, not a claim.
- Say each point once, on the page whose section brief covers it. Other pages link to that page.
- The wiki never comments on a paper's quality, layout, consistency or errors (for example a caption under the wrong table, or a missing version number). It records what the paper states; where the paper is silent, the item is "Not stated" or the page is empty.
- A page never describes how the wiki was built: it does not say where other passages were filed, what was searched for, or how its own sub-headings were chosen. A link to another page is enough.
- Stay inside the section.
- Link only to pages that exist. Other documents are written as plain text, always in the same form.
- Never state facts about the wiki from memory. Counts are counted from the pages, not estimated.
- Each section is broken into sub-headings by subject. Sub-headings follow the papers' own headings where they have them, never one heading per location.

## Workflow: Ingest
- Register the source before anything is extracted: client, document title, version, date, status and owner where the paper states them, and a content hash. A source whose hash matches one already ingested is not ingested again; a new version of the same paper supersedes the old one under Contradictions and updates.
- Read the paper's document control, purpose and scope first and record them in Overview and status. Then assign every passage a kind: policy or method, result, open item, cited standard, illustration, reasoning or editorial.
- Separate editorial material before any claim is drawn: footnotes, comments and notes. They are quoted only as editorial claims. A cover page and document control table (title, client, version, date, status, author, reviewer, owner, revision history) are not editorial: they supply the source page's facts and the version history in Overview and status. A table of contents is discarded.
- Split the text into passages using the paper's own headings, and give every claim one location in the form set out in Writing page text.
- Extract claims against the section briefs. Every claim carries its quote, character offsets, location, statement kind, subject, force and the version of the paper it comes from.
- Verify every claim, then file it to the section its brief routes it to. A claim that names no section of the fifteen is discarded and counted.
- Where a section is split, a passage routed to it is filed to the subtopic page of its group. This applies also when the section was split by an earlier upload: a later passage goes to the subtopic page of its group, or to a new subtopic page named after its nearest heading, and never onto the section's index page. The section's own page is then written as the index of its subtopic pages.
- Check coverage: every passage has at least one claim, or is recorded as stating nothing that can be claimed. Gaps are listed, never filled by inference.
- Rebuild the affected pages, then run the checks in Workflow: Maintain.

## Workflow: Answer and check
- To answer, choose pages from the page list, read them, and follow links (a section's index to its subtopic pages, and cross-links) until the question is answered. Cite only what supports the answer; list only cited pages. Where a question covers more than one section, answer each part from the page that covers it.
- Every statement in an answer rests on a claim and cites its location. Nothing is stated that no claim supports.
- An answer keeps each claim's force, values and conditions, and says when it relies on a draft paper, a result or an open item.
- This wiki answers what the client's papers say. It never answers what a standard requires; that question goes to the standard's wiki.
- Before saying the papers do not address something, search every section for the terms involved. Only then say it is not addressed, and say what was searched for.
- An answer worth keeping is filed as a synthesis page.

## Workflow: Maintain
- After every ingest, run these checks. All must pass:
  1. every claim has a location and a quote found at its offsets in the source;
  2. no claim from a result, open item, cited standard, illustration, reasoning or editorial passage carries statement kind policy or method;
  3. no claim is a heading, a table fragment or a pointer only;
  4. no two claims share a location and overlapping offsets;
  5. no unsupported claim is rendered;
  6. every passage has a claim or is recorded as stating nothing claimable.
- After a page is written, it is checked against the lists in Checks: every listed item and every condition phrase of each passage appears; every sentence that needs an opener carries one; a source page has its listed parts and no more than the allowed key takeaways; every decision point marked for the Judgements section has its line; and no citation is flagged. Subtopic pages are checked one by one. A page that fails is sent back with the list of failures, at most twice.
- Each ingest reports: claims by statement kind and by section, verification results, claims discarded by reason, and coverage gaps.

## Checks
The engine reads these lists to route passages, to split sections into subtopic pages and, after a page is written, to check it as set out in Workflow: Maintain. It reads the words only from here: a list that is missing switches off what uses it.
- Paragraph kinds (as the document reader names them): table = policy or method unless its heading marks it as results; footnote = editorial note; note = editorial note; comment = editorial note
- Openers: result = "The <document> reports"; open item = "The <document> notes as outstanding"; cited standard = "The <document> cites"; illustration = "In <example label>," (any label from Example labels, e.g. "In Illustration 2,"), "In the illustration on <title>,"; editorial note = "The editorial note states"; reasoning = "The <document> explains that"
- Linking words allowed before an opener: "However,", "In addition,", "For example,", "Alternatively,", "Similarly,", "Furthermore,", "Nevertheless,", "Conversely,", "Hence,", "Consequently,", "Accordingly,", "Instead,", "Moreover,", "In contrast,", "In that case,", "Specifically,". Any lead-in of up to four words ending in a comma may come before an opener; the list above gives examples.
- Lettered part forms: "(a)", "(i)", "a)", "1.", "•"
- Condition phrases: "only if", "unless", "except", "subject to", "regardless of", "despite", "notwithstanding", "at least", "more than", "less than", "within"
- Open-item phrases (a passage holding one is an open item): "to be completed", "to be confirmed", "TBC", "TBD", "work in progress", "future enhancement", "will be developed", "remains outstanding", "outstanding item", "outstanding items". A phrase counts only as written here: "outstanding" on its own (as in "outstanding balance") is not an open-item phrase.
- Source-page parts: what the document is = client, title, version, date, status, owner; purpose and scope = stated purpose; sections it informs = informed sections; key takeaways as linked claims = cited claims
- Key takeaways: at most 5
- Examples section: 14
- Kinds routed to the examples section: illustration
- Example labels: "Example <n>", "Illustration <n>", "Worked example <n>"
- Split sections (section number = what each subtopic page is grouped by): 14 = the section of the fifteen that owns the method each illustration illustrates; 11 = the section each line points to. An item matching Example labels is never split across pages; a group over the page size limit splits between items only.
- Page size limit: 6000 words. A section over this is split by the source's headings at the highest level that divides it; a group still over the limit is split again one level down. After writing, a sub-page is split again one level down only if it is more than 10% over the limit. A document's title heading (the heading above the whole document) is not a heading group for splitting; a sub-page is named after the nearest heading below it.
- Subtopic page minimum: 1500 words. A group under this is joined to the group before it under the same parent heading (or the one after it, if it is first). A join that would take a group over the page size limit goes to the group on the other side instead; if both would go over, the small group stays as its own page.
- Papers kept apart: a page that holds more than one paper keeps each paper's text under its own headings, and a split groups headings within one paper only.
- Document control headers (a table whose header row names at least two of these is a document control table): version · date · author · reviewer · approver · status · change · changes · revision · owner
- Pages that hold no claims: overview, section index pages
- Empty section text: "Empty." (the whole body of a section page that holds no claims)
- Absence phrases (allowed only on the source page and in Overview and status): "not stated", "does not address", "do not address", "not addressed", "searched"
- Overview lines: one per section of the fifteen, each ending with a link to the section's page if it holds claims, or the word "Empty" if it holds none
- Section slug: <nn>-<section name>
- Citations inherited by lists: a list item, table row, formula line, or formula-term list directly under a cited introducing line takes that line's citation
- Skipped headings: References · Bibliography · Table of contents. A passage under one of these headings is skipped like a stub: not written up and not checked.
- Stub forms: [Deleted] · Intentionally left blank · This page is intentionally left blank. A passage matching a stub form is not written up and not checked.
- Citation forms for unlabelled text: heading path as printed, joined by " > "; "Cover" for text before the first heading; "Document control" for a document control or revision history table; a footnote is cited by the location of the passage that carries its marker
