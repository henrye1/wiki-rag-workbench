# Reader settings (IFRS publisher PDFs)

The PDF reader takes every publisher word it relies on from this file: the headings that start and end a Standard's
own text, its appendices, the prefixes of paragraph numbers, and the fonts and page positions of the publisher's
layout. The code holds none of them. Each line is "- name: value"; a list is several lines under one heading. A change
here applies to the next upload; documents already read keep the text they were read with.

## Where a Standard's own text starts
A heading that begins with one of these (any case) starts the Standard's own text.
- International Financial Reporting Standard
- International Accounting Standard

## Appendices of a Standard
A heading that is exactly one of these (any case) starts that appendix; its paragraphs take the reader kind after "=".
A heading that names what an appendix holds comes after its letter heading and decides its kind, whatever its letter:
IAS Standards print their application guidance as Appendix A (IAS 39, IAS 21) or as an unlettered appendix (IAS 32),
and their amendments to other pronouncements as Appendix B. IAS 36 prints its guidance on present value techniques
as Appendix A, named only by its own heading.
- Appendix A = appendix_a
- Appendix B = appendix_b
- Appendix C = appendix_c
- Application guidance = appendix_b
- Amendments to other pronouncements = appendix_c
- Amendment to IAS 16 = appendix_c
- Using present value techniques to measure value in use = appendix_b

## Where a Standard's own text ends
A heading that begins with one of these (any case) ends the Standard's own text: what follows is not read as part of it.
- Approval by the Board
- Basis for Conclusions
- Dissenting

## Paragraph numbers in a Standard
The letters a paragraph number may start with, before its digits ("B5.5.17", "C2", "BA.1", and in IAS Standards
"AG14A" for application guidance and "A1" for an appendix numbered by its letter). <letter> stands for any
capital letter.
- B<letter>.
- B
- C
- AG
- A
- BC
- BCZ
- IE
- IG

## Paragraph numbers in documents published with a Standard
The prefix of each paragraph number and the reader kind of its paragraphs. <up to 3 letters> stands for none to three
capital letters ("BC", "BCZ", "BCIN"). Text without such a number is read as the introduction.
- IE = example
- IG = implementation_guidance
- BC<up to 3 letters> = basis_for_conclusions
- DO = dissenting_opinion

## Kind shown before each paragraph of a document published with a Standard
The reader writes this, in brackets, before each paragraph of that kind ("(Illustrative example) ...").
- example = Illustrative example
- implementation_guidance = Implementation guidance
- basis_for_conclusions = Basis for Conclusions
- dissenting_opinion = Dissenting opinion

## Implementation guidance
Implementation guidance numbers its questions in their headings ("A.1 Practice of settling net: ..."), not in the margin.
- Title begins: Guidance on implementing
- Question letters: A-G
- Question label prefix: IG
- Introduction label: IG introduction

## Publisher fonts and page layout
Font names are matched by their start or by a part of them, as each line says; sizes are in points; positions are in
points from the top left of the page.
- Body font begins: Swift
- Heading font begins: HelveticaLTPro
- Smallest heading size: 9.4
- Editorial font contains: BoldCond
- Editorial box heading font: HelveticaLTPro-Bold
- Editorial box heading smaller than: 9
- Editorial box heading left of: 175
- Header and footer font contains: Roman
- Smallest header and footer size: 8.9
- Header above: 110
- Footer below: 720
- Paragraph numbers left of: 150
