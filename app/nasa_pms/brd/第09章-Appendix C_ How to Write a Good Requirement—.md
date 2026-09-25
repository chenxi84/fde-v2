# Appendix C: How to Write a Good Requirement—

Checklist
C.1 Use of Correct Terms not the solution. Ask, “Why do you need the
requirement?” The answer may point to the real
 Shall = requirement requirement.)
 Will = facts or declaration of purpose  Free of descriptions of operations? (Is this a need
the product should satisfy or an activity involv-
 Should = goal ing the product? Sentences like “The operator
shall…” are almost always operational statements
C.2 Editorial Checklist not requirements.)
Personnel Requirement Example Product Requirements
 The requirement is in the form “responsible party  The system shall operate at a power level of…
shall perform such and such.” In other words, use
the active, rather than the passive voice. A require-  The software shall acquire data from the…
ment should state who shall (do, perform, provide,
weigh, or other verb) followed by a description of  The structure shall withstand loads of…
what should be performed.
 The hardware shall have a mass of…
Product Requirement
 The requirement is in the form “product ABC shall C.3 General Goodness Checklist
XYZ.” A requirement should state “The product
shall” (do, perform, provide, weigh, or other verb)  The requirement is grammatically correct.
followed by a description of what should be done.
 The requirement is free of typos, misspellings,
 The requirement uses consistent terminology to and punctuation errors.
refer to the product and its lower-level entities.
 The requirement complies with the project’s tem-
 Complete with tolerances for qualitative/perfor- plate and style rules.
mance values (e.g., less than, greater than or equal
to, plus or minus, 3 sigma root sum squares).  The requirement is stated positively (as opposed to
negatively, i.e., “shall not”).
 Is the requirement free of implementation?
(Requirements should state WHAT is needed,  The use of “To Be Determined” (TBD) values
NOT HOW to provide it; i.e., state the problem should be minimized. It is better to use a best
197

Appendix C: How to Write a Good Requirement— Checklist
estimate for a value and mark it “To Be Resolved” as TBDs or TBRs and a complete listing of them
(TBR) with the rationale along with what should maintained with the requirements?
be done to eliminate the TBR, who is responsi-
ble for its elimination, and by when it should be  Are any requirements missing? For example,
eliminated. have any of the following requirements areas
been overlooked: functional, performance, inter-
 The requirement is accompanied by an intel- face, environment (development, manufacturing,
ligible rationale, including any assumptions. test, transport, storage, and operations), facility
Can you validate (concur with) the assump- (manufacturing, test, storage, and operations),
tions? Assumptions should be confirmed before transportation (among areas for manufacturing,
baselining. assembling, delivery points, within storage facil-
ities, loading), training, personnel, operability,
 The requirement is located in the proper section of safety, security, appearance and physical charac-
the document (e.g., not in an appendix). teristics, and design.
C.4 Requirements Validation  Have all assumptions been explicitly stated?
Checklist
Compliance
Clarity  Are all requirements at the correct level (e.g., sys-
 Are the requirements clear and unambiguous? tem, segment, element, subsystem)?
(Are all aspects of the requirement understand-
able and not subject to misinterpretation? Is the  Are requirements free of implementation specif-
requirement free from indefinite pronouns (this, ics? (Requirements should state what is needed,
these) and ambiguous terms (e.g., “as appropri- not how to provide it.)
ate,” “etc.,” “and/or,” “but not limited to”)?)
 Are requirements free of descriptions of opera-
 Are the requirements concise and simple? tions? (Don’t mix operation with requirements:
update the ConOps instead.)
 Do the requirements express only one thought per
requirement statement, a stand-alone statement as  Are requirements free of personnel or task assign-
opposed to multiple requirements in a single state- ments? (Don’t mix personnel/task with product
ment, or a paragraph that contains both require- requirements: update the SOW or Task Order
ments and rationale? instead.)
 Does the requirement statement have one subject Consistency
and one predicate?  Are the requirements stated consistently without
contradicting themselves or the requirements of
Completeness related systems?
 Are requirements stated as completely as possible?
Have all incomplete requirements been captured  Is the terminology consistent with the user and
sponsor’s terminology? With the project glossary?
198

Appendix C: How to Write a Good Requirement— Checklist
 Is the terminology consistently used throughout  Is each performance requirement realistic?
the document? Are the key terms included in the
project’s glossary?  Are the tolerances overly tight? Are the tolerances
defendable and cost-effective? Ask, “What is the
Traceability worst thing that could happen if the tolerance was
 Are all requirements needed? Is each requirement doubled or tripled?”
necessary to meet the parent requirement? Is each
requirement a needed function or characteristic? Interfaces
Distinguish between needs and wants. If it is not  Are all external interfaces clearly defined?
necessary, it is not a requirement. Ask, “What is
the worst that could happen if the requirement  Are all internal interfaces clearly defined?
was not included?”
 Are all interfaces necessary, sufficient, and consis-
 Are all requirements (functions, structures, and tent with each other?
constraints) bidirectionally traceable to high-
er-level requirements or mission or system-of-in- Maintainability
terest scope (i.e., need(s), goals, objectives,  Have the requirements for maintainability of the
constraints, or concept of operations)? system been specified in a measurable, verifiable
manner?
 Is each requirement stated in such a manner that it
can be uniquely referenced (e.g., each requirement  Are requirements written so that ripple effects
is uniquely numbered) in subordinate documents? from changes are minimized (i.e., requirements
are as weakly coupled as possible)?
Correctness
 Is each requirement correct? Reliability
 Are clearly defined, measurable, and verifiable
 Is each stated assumption correct? Assumptions reliability requirements specified?
should be confirmed before the document can be
baselined.  Are there error detection, reporting, handling,
and recovery requirements?
 Are the requirements technically feasible?
 Are undesired events (e.g., single-event upset, data
Functionality loss or scrambling, operator error) considered and
 Are all described functions necessary and together their required responses specified?
sufficient to meet mission and system goals and
objectives?  Have assumptions about the intended sequence
of functions been stated? Are these sequences
Performance required?
 Are all required performance specifications and
margins listed (e.g., consider timing, throughput,  Do these requirements adequately address the
storage size, latency, accuracy and precision)? survivability after a software or hardware fault of
199

Appendix C: How to Write a Good Requirement— Checklist
the system from the point of view of hardware,  Are the requirements free of unverifiable terms
software, operations, personnel and procedures? (e.g., flexible, easy, sufficient, safe, ad hoc, ade-
quate, accommodate, user-friendly, usable, when
Verifiability/Testability required, if required, appropriate, fast, portable,
 Can the system be tested, demonstrated, light-weight, small, large, maximize, minimize,
inspected, or analyzed to show that it satisfies sufficient, robust, quickly, easily, clearly, other
requirements? Can this be done at the level of the “ly” words, other “ize” words)?
system at which the requirement is stated? Does
a means exist to measure the accomplishment of Data Usage
the requirement and verify compliance? Can the  Where applicable, are “don’t care” conditions
criteria for verification be stated? truly “don’t care”? (“Don’t care” values identify
cases when the value of a condition or flag is irrel-
 Are the requirements stated precisely to facilitate evant, even though the value may be important
specification of system test success criteria and for other cases.) Are “don’t care” conditions values
requirements? explicitly stated? (Correct identification of “don’t
care” values may improve a design’s portability.)
200
