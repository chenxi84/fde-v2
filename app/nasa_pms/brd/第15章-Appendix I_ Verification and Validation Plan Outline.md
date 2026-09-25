# Appendix I: Verification and Validation Plan Outline

Sample Outline requirements (verification) and to establish that the sys-
tem will meet the customers’ expectations (validation).
The Verification and Validation (V&V) Plan needs
to be baselined after the comments from PDR are 1.2 Responsibility and Change
incorporated. In this annotated outline, the use of Authority
the term “system” is indicative of the entire scope for This section will identify who has responsibility for the
which this plan is developed. This may be an entire maintenance of this plan and who or what board has the
spacecraft, just the avionics system, or a card within authority to approve any changes to it.
the avionics system. Likewise, the terms “end item,”
“subsystem,” or “element” are meant to imply the 1.3 Definitions
lower-level products that, when integrated together, This section will define any key terms used in the plan.
will produce the “system.” The general term “end item” The section may include the definitions of verification,
is used to encompass activities regardless of whether validation, analysis, test, demonstration, and test. See
the end item is a hardware or software element. appendix B of this handbook for definitions of these and
other terms that might be used.
The various sections are intended to move from the
high-level generic descriptions to the more detailed.
2.0 Applicable and Reference
The sections also flow from the lower-level items in
Documents
the product layer to larger and larger assemblies and
to the completely integrated system. The sections also
describe how that system may be integrated and fur- 2.1 Applicable Documents
ther verified/validated with its externally interfacing These are the documents that may impose additional
elements. This progression will help build a complete requirements or from which some of the requirements
understanding of the overall plans for verification have been taken.
and validation.
2.2 Reference Documents
These are the documents that are referred to within the
1.0 Introduction
V&V Plan that do not impose requirements, but which
1.1 Purpose and Scope may have additional useful information.
This section states the purpose of this Verification and
Validation Plan and the scope (i.e., systems) to which 2.3 Order of Precedence
it applies. The purpose of the V&V Plan is to identify This section identifies which documents take precedence
the activities that will establish compliance with the whenever there are conflicting requirements.
216

3.0 System Description
in the sections above. This may be an existing control
3.1 System Requirements Flowdown center, training facility, or other support.
This section describes where the requirements for this
system come from and how they are flowed down to
4.0 Verification and Validation
subsystems and lower-level elements. It should also
Process
indicate what method will be used to perform the flow-
down and bidirectional traceability of the requirements:
spreadsheet, model, or other means. It can point to the This section describes the process that will be used to per-
file, document, or spreadsheet that captures the actual form verification and validation.
requirements flowdown.
4.1 Verification and Validation
3.2 System Architecture Management Responsibilities
This section describes the system that is within the scope This section describes the responsibilities of key players
of this V&V Plan. The description should be enough so in the V&V activities. It may include identification and
that the V&V activities will have the proper context and duty description for test directors/conductors, managers,
be understandable. facility owners, boards, and other key stakeholders.
3.3 End Item Architectures 4.2 Verification Methods
This section describes each of the major end items (sub- This section defines and describes the methods that will
systems, elements, units, modules, etc.) that when inte- be used during the verification activities.
grated together, will form the overall system that is the
scope of this V&V Plan. 4.2.1 Analysis
Defines what this verification method means (See
3.3.1 System End Item A Appendix B of this handbook) and how it will be
This section describes the first major end item/subsystem applied to this system.
in more detail so that the V&V activities have context
and are understandable. 4.2.2 Inspection
Defines what this verification method means (See
3.3.n System End Item n Appendix B of this handbook) and how it will be
Each end item/subsystem is separately described in a sim- applied to this system.
ilar manner as above.
4.2.3 Demonstration
3.4 Ground Support Equipment Defines what this verification method means (See
This section describes any major ground-support equip- Appendix B of this handbook) and how it will be applied
ment that will be used during the V&V activities. This to this system.
may include carts for supplying power or fuel, special test
fixtures, lifting aids, simulators, or other type of support. 4.2.4 Test
Defines what this verification method means (See
3.5 Other Architecture Descriptions Appendix B of this handbook) and how it will be applied
This section describes any other items that are import- to this system. This category may need to be broken down
ant for the V&V activities but which are not included into further categories.
217

4.2.4.1 Qualification Testing 4.2.4 Test
This section describes the test philosophy for the envi- Defines what this validation method means (See
ronmental and other testing that is performed at higher Appendix B of this handbook) and how it will be applied
than normal levels to ascertain margins and perfor- to this system. This category may need to be broken down
mance in worst-case scenarios. Includes descriptions into further categories such as end-to-end testing, testing
of how the minimum and maximum extremes will be with humans, etc.)
determined for various types of tests (thermal, vibra-
tion, etc.), whether it will be performed at a component, 4.4 Certification Process
subsystem, or system level, and the pedigree (flight unit, Describes the overall process by which the results of these
qualification unit, engineering unit, etc.) of the units verification and validation activities will be used to cer-
these tests will be performed on. tify that the system meets its requirements and expec-
tations and is ready to be put into the field or fly. In
4.2.4.2 Other Testing addition to the verification and validation results, the
This section describes any other testing that will be used certification package may also include special forms,
as part of the verification activities that are not part reports, safety documentation, drawings, waivers, or
of the qualification testing. It includes any testing of other supporting documentation.
requirements within the normal operating range of the
end item. It may include some engineering tests that will 4.5 Acceptance Testing
form the foundation or provide dry runs for the official Describes the philosophy of how/which of the verification/
verification testing. validation activities will be performed on each of the
operational units as they are manufactured/coded and
4.3 Validation Methods are readied for flight/use. Includes how/if data packages
This section defines and describes the methods to be used will be developed and provided as part of the delivery.
during the validation activities.
5.0 Verification and Validation
4.2.1 Analysis
Implementation
Defines what this validation method means (See
Appendix B of this handbook) and how it will be applied
to this system. 5.1 System Design and Verification
and Validation Flow
4.2.2 Inspection This section describes how the system units/modules will
Defines what this validation method means (See flow from manufacturing/coding through verification
Appendix B of this handbook) and how it will be applied and validation. Includes whether each unit will be veri-
to this system. fied/validated separately, or assembled to some level and
then evaluated or other statement of flow.
4.2.3 Demonstration
Defines what this validation method means (See 5.2 Test Articles
Appendix B of this handbook) and how it will be applied This section describes the pedigree of test articles that will
to this system. be involved in the verification/validation activities. This
218

may include descriptions of breadboards, prototypes, 6.1.1 Developmental/Engineering Unit Evaluations
engineering units, qualification units, protoflight units, This section describes what kind of testing, analysis,
flight units, or other specially named units. A definition demonstrations, or inspections the prototype/engineering
of what is meant by these terms needs to be included to or other types of units/modules will undergo prior to per-
ensure clear understanding of the expected pedigree of forming official verification and validation.
each type of test article. Descriptions of what kind of test/
analysis activities will be performed on each type of test 6.1.2 Verification Activities
article is included. This section describes in detail the verification activities
that will be performed on this end item.
5.3 Support Equipment
This section describes any special support equipment that 6.1.2.1 Verification by Testing
will be needed to perform the verification/validation This section describes all verification testing that will be
activities. This will be a more detailed description than performed on this end item.
is stated in Section 3.4 of this outline.
6.1.2.1.1 Qualification Testing
5.4 Facilities This section describes the test environmental and other
This section identifies and describes major facilities that testing that is performed at higher than normal levels
will be needed in order to accomplish the verification to ascertain margins and performance in worst-case
and validation activities. These may include environ- scenarios. It includes what minimum and maximum
mental test facilities, computational facilities, simula- extremes will be used on qualification tests (thermal,
tion facilities, training facilities, test stands, and other vibration, etc.) of this unit, whether it will be performed
facilities as needed. at a component, subsystem, or system level, and the ped-
igree (flight unit, qualification unit, engineering unit,
etc.) of the units these tests will be performed on.
6.0 End Item Verification and
Validation
6.1.2.1.2 Other Testing
This section describes all other verification tests that are
This section describes in detail the V&V activities that not performed as part of the qualification testing. These
will be applied to the lower-level subsystems/elements/ will include verification of requirements in the normal
end items. It can point to other stand-alone descrip- operating ranges.
tions of these tests if they will be generated as part of
organizational responsibilities for the products at each 6.1.2.2 Verification by Analysis
product layer. This section describes the verifications that will be per-
formed by analysis (including verification by similarity).
6.1 End Item A This may include thermal analysis, stress analysis, anal-
This section focuses in on one of the lower-level end items ysis of fracture control, materials analysis, Electrical,
and describes in detail what type of verification activi- Electronic, and Electromechnical (EEE) parts analysis,
ties it will undergo. and other analyses as needed for the verification of this
end item.
219

7.0 System Verification and
6.1.2.3 Verification by Inspection
Validation
This section describes the verifications that will be per-
formed for this end item by inspection. 7.1 End-Item Integration
This section describes how the various end items will be
6.1.2.4 Verification Demonstration assembled/integrated together, verified and validated.
This section describes the verifications that will be per- For example, the avionics and power systems may be
formed for this end item by demonstration. integrated and tested together to ensure their interfaces
and performance is as required and expected prior to
6.1.3 Validation Activities integration with a larger element. This section describes
6.1.3.1 Validation by Testing the verification and validation that will be performed
This section describes what validation tests will be per- on these major assemblies. Complete system integration
formed on this end item. will be described in later sections.
6.1.3.2 Validation by Analysis 7.1.1 Developmental/Engineering Unit Evaluations
This section describes the validation that will be per- This section describes the unofficial (not the formal ver-
formed for this end item through analysis. ification/validation) testing/analysis that will be per-
formed on the various assemblies that will be tested
6.1.3.3 Validation by Inspection together and the pedigree of the units that will be used.
This section describes the validation that will be per- This may include system-level testing of configurations
formed for this end item through inspection. using engineering units, breadboard, simulators, or
other forms or combination of forms.
6.1.3.4 Validation by Demonstration
This section describes the validations that will be per- 7.1.2 Verification Activities
formed for this end item by demonstration. This section describes the verification activities that will
be performed on the various assemblies.
6.1.4 Acceptance Testing
This section describes the set of tests, analysis, demonstra- 7.1.2.1 Verification by Testing
tions, or inspections that will be performed on the flight/ This section describes all verification testing that will be
final version of the end item to show it has the same performed on the various assemblies. The section may be
design as the one that is being verified, that the work- broken up to describe qualification testing performed on
manship on this end item is good, and that it performs the various assemblies and other types of testing.
the identified functions properly.
7.1.2.2 Verification by Analysis
6.n End Item n This section describes all verification analysis that will be
In a similar manner as above, a description of how each performed on the various assemblies.
end item that makes up the system will be verified and
validated is made. 7.1.2.3 Verification by Inspection
This section describes all verification inspections that
will be performed on the various assemblies.
220

7.1.2.4 Verification by Demonstration 7.2.2.1 Verification Testing
This section describes all verification demonstrations This section describes all verification testing that will be
that will be performed on the various assemblies. performed on the integrated system. The section may be
broken up to describe qualification testing performed at
7.1.3 Validation Activities the integrated system level and other types of testing.
7.1.3.1 Validation by Testing
This section describes all validation testing that will be 7.2.2.2 Verification Analysis
performed on the various assemblies. This section describes all verification analysis that will be
performed on the integrated system.
7.1.3.2 Validation by Analysis
This section describes all validation analysis that will be 7.2.2.3 Verification Inspection
performed on the various assemblies. This section describes all verification inspections that
will be performed on the integrated system.
7.1.3.3 Validation by Inspection
This section describes all validation inspections that will 7.2.2.4 Verification Demonstration
be performed on the various assemblies. This section describes all verification demonstrations
that will be performed on the integrated system.
7.1.3.4 Validation by Demonstration
This section describes all validation demonstrations that 7.2.3 Validation Activities
will be performed on the various assemblies. This section describes the validation activities that will
be performed on the completely integrated system.
7.2 Complete System Integration
This section describes the verification and validation 7.2.3.1 Validation by Testing
activities that will be performed on the systems after all This section describes all validation testing that will be
its assemblies are integrated together to form the complete performed on the integrated system.
integrated system. In some cases this will not be practical.
Rationale for what cannot be done should be captured. 7.2.3.2 Validation by Analysis
This section describes all validation analysis that will be
7.2.1 Developmental/Engineering Unit Evaluations performed on the integrated system.
This section describes the unofficial (not the formal
verification/validation) testing/analysis that will be 7.2.3.3 Validation by Inspection
performed on the complete integrated system and the This section describes the validation inspections that will
pedigree of the units that will be used. This may include be performed on the integrated system.
system-level testing of configurations using engineering
units, breadboard, simulators, or other forms or combi- 7.2.3.4 Validation by Demonstration
nation of forms. This section describes the validation demonstrations that
will be performed on the integrated system.
7.2.2 Verification Activities
This section describes the verification activities that will
be performed on the completely integrated system
221

8.0 Program Verification and
Appendix A: Acronyms and Abbreviations
Validation
This is a list of all the acronyms and abbreviations used
This section describes any further testing that the system in the V&V Plan and their spelled-out meaning.
will be subjected to. For example, if the system is an
instrument, the section may include any verification/vali- Appendix B: Definition of Terms
dation that the system will undergo when integrated into This section is a definition of the key terms that are used
its spacecraft/platform. If the system is a spacecraft, the in the V&V Plan.
section may include any verification/validation the system
will undergo when integrated with its launch vehicle. Appendix C: Requirement Verification
Matrix
8.1 Vehicle Integration The V&V Plan needs to be baselined after the comments
This section describes any further verification or valida- from PDR are incorporated. The information in this
tion activities that will occur when the system is inte- section may take various forms. It could be a pointer to
grated with its external interfaces. another document or model where the matrix and its
results may be found. This works well for large projects
8.2 End-to-End Integration using a requirements-tracking application. The infor-
This section describes any end-to-end testing that the mation in this section could also be the requirements
system may undergo. For example, this configuration matrix filled out with all but the results information and
would include data being sent from a ground control a pointer to where the results can be found. This allows
center through one or more relay satellites to the system the key information to be available at the time of base-
and back. lining. For a smaller project, this may be the completed
verification matrix. In this case, the V&V Plan would
8.3 On-Orbit V&V Activities be filled out as much as possible before. See Appendix D
This section describes any remaining verification/valida- for an example of a verification matrix.
tion activities that will be performed on a system after it
reaches orbit or is placed in the field. Appendix D: Validation Matrix
As with the verification matrix, this product may take
various forms from a completed matrix to just a pointer
9.0 System Certification
for where the information can be found. Appendix E
Products
provides an example of a validation matrix.
This section describes the type of products that will
be generated and provided as part of the certification
process. This package may include the verification and
validation matrix and results, pressure vessel certifica-
tions, special forms, materials certifications, test reports
or other products as is appropriate for the system being
verified and validated.
222
