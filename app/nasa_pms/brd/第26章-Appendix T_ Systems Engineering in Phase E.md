# Appendix T: Systems Engineering in Phase E

T.1 Overview • Unforgiving schedule: Unlike pre-flight test
activities, it may be difficult or even impossible
In general, normal Phase E activities reflect a reduced to pause mission execution to deal with technical
emphasis on system design processes but a continued issues of a spacecraft in operation. It is typically
focus on product realization and technical manage- difficult or impossible to truly pause mission exe-
ment. Product realization process execution in Phase cution after launch.
E takes the form of continued mission plan generation
(and update), response to changing flight conditions These factors must be addressed when consider-
(and occurrence of in-flight anomalies), and update ing activities that introduce change and risk during
of mission operations techniques, procedures, and Phase E.
guidelines based on operational experience gained.
Technical management processes ensure that appro-
priate rigor and risk management practices are applied NOTE: When significant hardware or software
in the execution of the product realization processes. changes are required in Phase E, the logical decom-
position process may more closely resemble that
Successful Phase E execution requires the prior estab- exercised in earlier project phases. In such cases,
lishment of mission operations capabilities in four it may be more appropriate to identify the modifi-
(4) distinct categories: tools, processes, products, cation as a new project executing in parallel—and
and trained personnel. These capabilities may be coordinated with—the operating project.
developed as separate entities, but need to be fused
together in Phase E to form an end-to-end opera-
T.2 Transition from Development
tional capability.
to Operations
Although systems engineering activities and pro-
cesses are constrained throughout the entire project An effective transition from development to opera-
life cycle, additional pressures exist in Phase E: tions phases requires prior planning and coordina-
tion among stakeholders. This planning should focus
• Increased resource constraints: Even when not only on the effective transition of hardware and
additional funding or staffing can be secured, software systems into service but also on the effec-
building new capabilities or training new person- tive transfer of knowledge, skills, experience, and
nel may require more time or effort than is avail- processes into roles that support the needs of flight
able. Project budget and staffing profiles generally operations.
decrease at or before entry into Phase E, and the
remaining personnel are typically focused on mis- Development phase activities need to clearly and
sion execution. concisely document system knowledge in the form
254

of operational techniques, characteristics, limits, T.3.1.1 Stakeholder Expectations Definition
and constraints—these are key inputs used by flight Stakeholder expectations should have been identi-
operations personnel in building operations tools fied during development phase activities, including
and techniques. Phase D Integration and Test (I&T) the definition of operations concepts and design ref-
activities share many common needs with Phase E erence missions. Central to this definition is a con-
operations activities. Without prior planning and sensus on mission success criteria and the priority of
agreement, however, similar products used in these all intended operations. The mission operations plan
two phases may be formatted so differently that one should state and address these stakeholder expec-
set cannot be used for both purposes. The associated tations with regard to risk management practices,
product duplication is often unexpected and results planning flexibility and frequency of opportunities
in increased cost and schedule risk. Instead, system to update the plan, time to respond and time/scope
engineers should identify opportunities for product of status communication, and other key parameters
reuse early in the development process and establish of mission execution. Additional detail in the form
common standards, formats, and content expecta- of operational guidelines and constraints should be
tions to enable transition and reuse. incorporated in mission operations procedures and
flight rules.
Similarly, the transfer of skills and experience should
be managed through careful planning and placement The Operations Readiness Review (ORR) should
of key personnel. In some cases, key design, integra- confirm that stakeholders accept the mission opera-
tion, and test personnel may be transitioned into the tions plan and operations implementation products.
mission operations team roles. In other cases, dedi-
cated mission operations personnel may be assigned However, it is possible for events in Phase E to require
to shadow or assist other teams during Phase A–D a reassessment of stakeholder expectations. Significant
activities. In both cases, assignees bring knowledge, in-flight anomalies or scientific discoveries during
skills, and experience into the flight operations envi- flight operations may change the nature and goals of
ronment. Management of this transition process can, a mission. Mission systems engineers, mission oper-
however, be complex as these personnel may be con- ations managers, and program management need to
sidered key to both ongoing I&T and preparation for remain engaged with stakeholders throughout Phase
upcoming operations. Careful and early planning of E to identify potential changes in expectations and to
personnel assignments and transitions is key to suc- manage the acceptance or rejection of such changes
cess in transferring skills and experience. during operations.
T.3.1.2 Technical Requirements Definition
T.3 System Engineering
New technical requirements and changes to existing
Processes in Phase E
requirements may be identified during operations as
a result of:
T.3.1 System Design Processes
In general, system design processes are complete well • New understanding of system characteristics
before the start of Phase E. However, events during through flight experience;
operations may require that these processes be revis-
ited in Phase E. • The occurrence of in-flight anomalies; or
255

• Changing mission goals or parameters (such as Scarcity of time and resources during Phase E can
mission extension). make implementation of these design solutions chal-
lenging. The design solution needs to take into account
These changes or additions are generally handled as the availability of and constraints to resources.
change requests to an operations baseline already under
configuration management and possibly in use as part T.3.1.5 Product Implementation
of ongoing flight operations. Such changes are more Personnel who implement mission operations prod-
commonly directed to the ground segment or opera- ucts such as procedures and spacecraft command
tions products (operational constraints, procedures, scripts should be trained and certified to the appro-
etc.). Flight software changes may also be considered, priate level of skill as defined by the project. Processes
but flight hardware changes for anything other than governing the update and creation of operations
human-tended spacecraft are rarely possible. products should be in place and exercised prior to
Phase E.
Technical requirement change review can be more
challenging in Phase E as fewer resources are avail- T.3.2 Product Realization Processes
able to perform comprehensive review. Early and Product realization processes in Phase E are typically
close involvement of Safety and Mission Assurance executed by Configuration Management (CM) and
(SMA) representatives can be key in ensuring that test personnel. It is common for these people to be
proposed changes are appropriate and within the “shared resources;” i.e., personnel who fulfil other
project’s allowable risk tolerance. roles in addition to CM and test roles.
T.3.1.3 Logical Decomposition T.3.2.1 Product Integration
In general, logical decomposition of mission oper- Product integration in Phase E generally involves bring-
ations functions is performed during development ing together multiple operations products—some pre-
phases. Additional logical decomposition during existing and others new or modified—into a proposed
operations is more often applied to the operations update to the baseline mission operations capability.
products: procedures, user interfaces, and operational
constraints. The authors and users of these products The degree to which a set of products is integrated may
are often the most qualified people to judge the vary based on the size and complexity of the project.
appropriate decomposition of new or changed func- Small projects may define a baseline—and update to
tionality as a series of procedures or similar products. that baseline—that spans the entire set of all opera-
tions products. Larger or more complex projects may
T.3.1.4 Design Solution Definition choose to create logical baseline subsets divided along
Similar to logical decomposition, design solution practical boundaries. In a geographically disperse set
definition tasks may be better addressed by those who of separate mission operations Centers, for example,
develop and use the products. Minor modifications each Center may be initially integrated as a separate
may be handled entirely within an operations team product. Similarly, the different functions within a
(with internal reviews), while larger changes or addi- single large control Center—planning, flight dynam-
tions may warrant the involvement of program-level ics, command and control, etc.—may be established
system engineers and Safety and Mission Assurance as separately baselined products. Ultimately, however,
(SMA) personnel.
256

some method needs to be established to ensure that procedures may not be impacted by environmen-
the product realization processes identify and assess tal conditions at all.
all potential impacts of system changes.
T.3.2.3 Product Validation
T.3.2.2 Product Verification Product validation is generally executed through the
Product verification in Phase E generally takes the use of products in integrated operational scenarios
form of unit tests of tools, data sets, procedures, and such as mission simulations, operational readiness
other items under simulated conditions. Such “thread tests, and/or spacecraft end-to-end tests. In these
tests” may exercise single specific tasks or functions. environments, a collection of products is used by a
The fidelity of simulation required for verification team of operators to simulate an operational activ-
varies with the nature and criticality of the product. ity or set of activities such as launch, activation, ren-
Key characteristics to consider include: dezvous, science operations, or Entry, Descent, and
Landing (EDL). The integration of multiple team
• Runtime: Verification of products during flight members and operations products provides the con-
operations may be significantly time constrained. text necessary to determine if the product is appropri-
Greater simulation fidelity can result in slower ate and meets the true operations need.
simulation performance. This slower performance
may be acceptable for some verification activities T.3.2.4 Product Transition
but may be too constraining for others. Transition of new operational capabilities in Phase
E is generally overseen by the mission operations
• Level of detail: Testing of simple plans and pro- manager or a Configuration Control Board (CCB)
cedures may not require high-fidelity simulation chaired by the mission operations manager or the
of a system’s dynamics. For example, simple state project manager.
change processes may be tested on relatively
low-fidelity simulations. However, operational Proper transition management includes the inspec-
activities that involve dynamic system attributes – tion of product test (verification and validation)
such as changes in pressure, temperature, or other results as well as the readiness of the currently oper-
physical properties may require testing with much ating operations system to accept changes. Transition
higher-fidelity simulations. during Phase E can be particularly challenging as the
personnel using these capabilities also need to change
• Level of integration: Some operations may impact techniques, daily practices, or other behaviors as a
only a single subsystem, while others can affect result. Careful attention should be paid to planned
multiple systems or even the entire spacecraft. operations, such as spacecraft maneuvers or other
mission critical events and risks associated with per-
• Environmental effects: Some operations products forming product transition at times near such events.
and procedures may be highly sensitive to envi-
ronmental conditions, while others may not. For T.3.3 Technical Management
example, event sequences for atmospheric entry Processes
and deceleration may require accurate weather Technical management processes are generally a
data. In contrast, simple system reconfiguration shared responsibility of the project manager and
257

the mission operations manager. Clear agreement be the result of system failures or changes in the sur-
between these two parties is essential in ensuring that rounding environment. Where additional time may
Phase E efforts are managed effectively. be available to assess and mitigate risk in other proj-
ect phases, the nature of flight operations may limit
T.3.3.1 Technical Planning the time over which risk management can be exe-
Technical planning in Phase E generally focuses cuted. For this reason, every project should develop a
on the management of scarce product develop- formal process for handling anomalies and managing
ment resources during mission execution. Key risk during operations. This process should be exer-
decision-makers, including the mission operations cised before flight, and decision-makers should be
manager and lower operations team leads, need to well versed in the process details.
review the benefits of a change against the resource
cost to implement changes. Many resources are T.3.3.5 Configuration Management
shared in Phase E – for example, product developers Effective and efficient Configuration Management
may also serve other real-time operations roles– and (CM) is essential during operations. Critical oper-
the additional workload placed on these resources ations materials, including procedures, plans, flight
should be viewed as a risk to be mitigated during datasets, and technical reference material need to
operations. be secure, up to date, and easily accessed by those
who make and enact mission critical decisions. CM
T.3.3.2 Requirements Management systems—in their intended flight configuration—
Requirements management during Phase E is simi- should be exercised as part of operational readiness
lar in nature to pre-Phase E efforts. Although some tests to ensure that the systems, processes, and par-
streamlining may be implemented to reduce process ticipants are flight-ready.
overhead in Phase E, the core need to review and val-
idate requirements remains. As most Phase E changes Access to such operations products is generally
are derived from a clearly demonstrated need, pro- time-critical, and CM systems supporting that access
gram management may reduce or waive the need should be managed accordingly. Scheduled mainte-
for complete requirements traceability analysis and nance or other “downtime” periods should be coor-
documentation. dinated with flight operations plans to minimize
the risk of data being inaccessible during critical
T.3.3.3 Interface Management activities.
It is relatively uncommon for interfaces to change in
Phase E, but this can occur when a software tool is T.3.3.6 Technical Data Management
modified or a new need is uncovered. Interface defi- Tools, procedures, and other infrastructure for
nitions should be managed in a manner similar to Technical Data Management must be baselined,
that used in other project phases. implemented, and verified prior to flight operations.
Changes to these capabilities are rarely made during
T.3.3.4 Technical Risk Management Phase E due to the high risk of data loss or reduc-
Managing technical risks during operations can be tion in operations efficiency when changing during
more challenging during Phase E than during other operations.
phases. New risks discovered during operations may
258

Mandatory Technical Data Management infrastruc- phases. Phase E TPMs may focus on the accomplish-
ture changes, when they occur, should be carefully ment of mission events, the performance of the sys-
reviewed by those who interact with the data on a tem in operation, and the ability of the operations
regular basis. This includes not only operations per- team to support upcoming events.
sonnel, but also engineering and science customers of
that data. T.3.3.8 Decision Analysis
The Phase E Decision Analysis Process is similar to
T.3.3.7 Technical Assessment that in other project phases but may emphasize dif-
Formal technical assessments during Phase E are typ- ferent criteria. For example, the ability to change a
ically focused on the upcoming execution of a spe- schedule may be limited by the absolute timing of
cific operational activity such as launch, orbit entry, events such as an orbit entry or landing on a plan-
or decommissioning. Reviews executed while flight etary surface. Cost trades may be more constrained
operations are in progress should be scoped to answer by the inability to add trained personnel to support
critical questions while not overburdening the project an activity. Technical trades may be limited by the
or operations team. inability to modify hardware in operation.
Technical Performance Measures (TPMs) in Phase E
may differ significantly from those in other project
259

References Cited
This appendix contains references that were cited in Section 1.1 Purpose
the sections of the handbook. NPR 7123.1. Systems Engineering Processes and
Preface
NPR 7123.1, Systems Engineering Processes and Section 1.2 Scope and Depth
Requirements NASA Office of Chief Information Officer (OCIO),
Information Technology Systems Engineering
NASA Chief Engineer and the NASA Integrated Handbook Version 2.0
Action Team (NIAT) report, Enhancing Mission
Success – A Framework for the Future, December NASA-HDBK-2203, NASA Software Engineering
21, 2000. Authors: McBrayer, Robert O and Handbook (February 28, 2013)
Thomas, Dale, NASA Marshall Space Flight
Center, Huntsville, AL United States. Section 2.0 Fundamentals of Systems
Engineering
NASA. Columbia Accident Investigation Board NPR 7120.5, NASA Space Flight Program and
(CAIB) Report, 6 volumes: Aug. 26, Oct. 2003. Project Management Requirements
http://www.nasa.gov/columbia/caib/html/report.
html NPR 7120.7, NASA Information Technology and
Institutional Infrastructure Program and Project
NASA. Diaz Report, A Renewed Commitment to Management Requirements
Excellence: An Assessment of the NASA Agency-
wide Applicability of the Columbia Accident NPR 7120.8, NASA Research and Technology
Investigation Board Report, January 30, 2004. Program and Project Management
Mr. Al Diaz, Director, Goddard Space Flight Requirements
Center, and team.
NPR 7123.1, NASA Systems Engineering Processes
International Organization for Standardization and Requirements
(ISO) 9000:2015, Quality management sys-
tems – Fundamentals and vocabulary. Geneva: NASA Engineering Network (NEN) Systems
International Organization for Standardization, Engineering Community of Practice (SECoP),
2015. located at https://nen.nasa.gov/web/se
Griffin, Michael D., NASA Administrator.
“System Engineering and the Two Cultures
260

of Engineering.” Boeing Lecture, Purdue NPR 7123.1, NASA Systems Engineering Processes
University, March 28, 2007. and Requirements
Rechtin, Eberhardt. Systems Architecting of Section 3.0 NASA Program/Project Life
Organizations: Why Eagles Can’t Swim. Boca Cycle
Raton: CRC Press, 2000. NPR 7120.5, NASA Space Flight Program and
Project Management Requirements
Section 2.1 The Common Technical
Processes and the SE Engine NPR 7120.8, NASA Research and Technology
NPR 7123.1, NASA Systems Engineering Processes Program and Project Management
and Requirements Requirements
Society of Automotive Engineers (SAE) and the NASA Office of the Chief Information Officer
European Association of Aerospace Industries (OCIO), Information Technology Systems
(EAAI). AS9100C Quality Management Systems Engineering Handbook Version 2.0
(QMS) – Requirements for Aviation, Space, and
Defense Organizations Revision C: January 15, NASA/SP-2014-3705, NASA Space Flight Program
2009. and Project Management Handbook
Section 2.3 Example of Using the SE Section 3.1 Program Formulation
Engine NPR 7120.5, NASA Space Flight Program and
NPD 1001.0, 2006 NASA Strategic Plan Project Management Requirements
NPR 7120.5, NASA Space Flight Program and NPR 7120.7, NASA Information Technology and
Project Management Requirements Institutional Infrastructure Program and Project
Management Requirements
Section 2.5 Cost Effectiveness
Considerations NPR 7120.8, NASA Research and Technology
Department of Defense (DOD) Defense Acquisition Program and Project Management
University (DAU). Systems Engineering Requirements
Fundamentals Guide. Fort Belvoir, VA, 2001.
NPR 7123.1, NASA Systems Engineering Processes
INCOSE-TP-2003-002-04, Systems Engineering and Requirements
Handbook: A Guide for System Life Cycle Processes
and Activities, Version 4, edited by Walden, Section 3.2 Program Implementation
David D., et al., 2015 NPR 7120.5, NASA Space Flight Program and
Section 2.6 Human Systems Integration
(HSI) in the SE Process NPR 7123.1, NASA Systems Engineering Processes
NPR 7120.5, NASA Space Flight Program and and Requirements
261

Section 3.3 Project Pre-Phase A: Concept Section 3.6 Project Phase C: Final Design
Studies and Fabrication
NPR 7120.5, NASA Space Flight Program and NPR 7120.5, NASA Space Flight Program and
Project Management Requirements Project Management Requirements
NPR 7123.1, NASA Systems Engineering Processes NPR 7123.1, NASA Systems Engineering Processes
and Requirements and Requirements
Section 3.4 Project Phase A: Concept and Section 3.7 Project Phase D: System
Technology Development Assembly, Integration and Test, Launch
NPD 1001.0, 2014 NASA Strategic Plan NPR 7120.5, NASA Space Flight Program and
NPR 2810.1, Security of Information Technology
NPR 7123.1, NASA Systems Engineering Processes
NPR 7120.5, NASA Space Flight Program and and Requirements
NASA Office of the Chief Information Officer
NPR 7123.1, NASA Systems Engineering Processes (OCIO), Information Technology Systems
and Requirements Engineering Handbook Version 2.0
NPR 7150.2, NASA Software Engineering Section 3.8 Project Phase E: Operations
Requirements and Sustainment
NPR 7120.5, NASA Space Flight Program and
NASA-STD-8719.14, Handbook for Limiting Orbital Project Management Requirements
Debris. Rev A with Change 1. December 8,
2011. NPR 7123.1, NASA Systems Engineering Processes
and Requirements
National Institute of Standards and Technology
(NIST), Federal Information Processing Section 3.9 Project Phase F: Closeout
Standard Publication (FIPS PUB) 199, NPR 7120.5, NASA Space Flight Program and
Standards for Security Categorization of Federal Project Management Requirements
Information and Information Systems, February
2004. NPR 7123.1, NASA Systems Engineering Processes
and Requirements
Section 3.5 Project Phase B: Preliminary
Design and Technology Completion NPD 8010.3, Notification of Intent to
NPR 7120.5, NASA Space Flight Program and Decommission or Terminate Operating Space
Project Management Requirements Systems and Terminate Missions
NPR 7123.1, NASA Systems Engineering Processes NPR 8715.6, NASA Procedural Requirements for
and Requirements Limiting Orbital Debris
262

Section 3.10 Funding: The Budget Cycle Presidential Policy Directive PPD-4 (2010),
NASA’s Financial Management Requirements (FMR) National Space Policy
Volume 4
Presidential Policy Directive PPD-21 (2013), Critical
Section 3.11 Tailoring and Customization Infrastructure Security and Resilience
of NPR 7123.1 Requirements
NPD 1001.0, 2014 NASA Strategic Plan Ball, Robert E. (Naval Postgraduate School), The
Fundamentals of Aircraft Combat Survivability
NPR 7120.5, NASA Space Flight Program and Analysis and Design, 2nd Edition, AIAA
Project Management Requirements Education Series, 2003
NPR 7120.7, NASA Information Technology and Larson (Wiley J.), Kirkpatrick, Sellers, Thomas,
Institutional Infrastructure Program and Project and Verma. Applied Space Systems Engineering:
Management Requirements A Practical Approach to Achieving Technical
Baselines. 2nd Edition, Boston, MA: McGraw-
NPR 7120.8, NASA Research and Technology Hill Learning Solutions, CEI Publications,
Program and Project Management 2009.
Section 4.2 Technical Requirements
NPR 7123.1, NASA Systems Engineering Processes Definition
and Requirements NPR 7120.10, Technical Standards for NASA
Programs and Projects
NPR 7150.2, NASA Software Engineering
Requirements NPR 8705.2, Human-Rating Requirements for
Space Systems
NPR 8705.4, Risk Classification for NASA Payloads
NPR 8715.3, NASA General Safety Program
NASA-HDBK-2203, NASA Software Engineering Requirements
Handbook (February 28, 2013)
NASA-STD-3001, NASA Space Flight Human
NASA Engineering Network (NEN) Systems System Standard – 2 volumes
Engineering Community of Practice (SECoP),
located at https://nen.nasa.gov/web/se NASA-STD-8719.13, Software Safety Standard, Rev
C. Washington, DC, May 7, 2013.
Section 4.1 Stakeholder Expectations
Definition NASA/SP-2010-3407, Human Integration Design
NPR 7120.5, NASA Space Flight Program and Handbook (HIDH)
NASA Science Mission Directorate strategic plans
263

Section 4.3 Logical Decomposition (QMS)—Requirements for Aviation, Space, and
Department of Defense (DOD) Architecture Defense Organizations Revision C: 2009-01-15
Framework (DODAF) Version 2.02 Change 1,
January 2015 Blanchard, Benjamin S., System Engineering
Management. 4th Edition, Hoboken, NJ: John
Institute of Electrical and Electronics Engineers Wiley & Sons, Inc., 2008
(IEEE) STD 610.12-1990, IEEE Standard
Glossary of Software Engineering Terminology. Section 5.1 Product Implementation
Reaffirmed 2002. Superseded by ISO/IEC/ NPR 7150.2, NASA Software Engineering
IEEE 24765:2010, Systems and Software Requirements
Engineering – Vocabulary
NASA Engineering Network (NEN) Systems
Section 4.4 Design Solution Definition Engineering Community of Practice (SECoP),
NPD 8730.5, NASA Quality Assurance Program located at https://nen.nasa.gov/web/se
Policy
NASA Engineering Network (NEN) V&V
NPR 8735.2, Management of Government Quality Community of Practice, located at https://nen.
Assurance Functions for NASA Contracts nasa.gov/web/se
NASA-HDBK-1002, Fault Management (FM) American Institute of Aeronautics and Astronautics
Handbook, Draft 2, April 2012. (AIAA) G-118-2006e. AIAA Guide for
Managing the Use of Commercial Off the Shelf
NASA-STD-3001, NASA Space Flight Human (COTS) Software Components for Mission-
System Standard – 2 volumes Critical Systems. Reston, VA, 2006
NASA-STD-8729.1, Planning, Developing, and Section 5.2 Product Integration
Maintaining an Effective Reliability and NASA Lyndon B. Johnson Space Center (JSC-
Maintainability (R&M) Program. Washington, 60576), National Space Transportation System
DC, December 1, 1998. (NSTS), Space Shuttle Program, Transition
Management Plan, May 9, 2007
Code of Federal Regulations (CFR), Title 48 –
Federal Acquisition Regulation (FAR) System, Section 5.3 Product Verification
Part 46.4 Government Contract Quality NPR 7120.5, NASA Space Flight Program and
Assurance (48 CFR 46.4) Project Management Requirements
International Organization for Standardization, ISO NPR 7120.8, NASA Research and Technology
9001:2015 Quality Management Systems (QMS) Program and Project Management
Society of Automotive Engineers and the
European Association of Aerospace Industries. NPR 7123.1, NASA Systems Engineering Processes
AS9100C Quality Management Systems and Requirements
264

NPR 8705.4, Risk Classification for NASA Payloads NASA-SP-2010-3404, NASA Work Breakdown
Structure Handbook
NASA-STD-7009, Standard for Models and
Simulations. Washington, DC, October 18, NASA Cost Estimating Handbook (CEH), Version 4,
2013 February 2015.
NASA GSFC-STD-7000, Goddard Technical DOD. MIL-STD-881C, Work Breakdown Structure
Standard: General Environmental Verification (WBS) for Defense Materiel Items. Washington,
Standard (GEVS) for GSFC Flight Programs and DC, October 3, 2011.
Projects. Goddard Space Flight Center. April
2005 Institute of Electrical and Electronics Engineers
(IEEE) STD 1220-2005. IEEE Standard for
Department of Defense (DOD). MIL-STD-1540D, Application and Management of the Systems
Product Verification Requirements for Launch, Engineering Process, Washington, DC, 2005.
Upper Stage, and Space Vehicles. January 15,
1999 Office of Management and Budget (OMB) Circular
A-94, “Guidelines and Discount Rates for
Section 5.4 Product Validation Benefit-Cost Analysis of Federal Programs”
NPD 7120.4, NASA Engineering and Program/ (10/29/1992)
Project Management Policy
Joint (cost and schedule) Confidence Level (JCL).
NPR 7150.2, NASA Software Engineering Frequently asked questions (FAQs) can be found
Requirements at: http://www.nasa.gov/pdf/394931main_JCL_
FAQ_10_12_09.pdf
Section 5.5 Product Transition
(The) National Environmental Policy Act of 1969 The U. S. Chemical Safety Board (CSB) case study
(NEPA). See 42 U.S.C. 4321-4347. https://ceq. reports on mishaps found at: http://www.csb.gov/
doe.gov/welcome.html
Section 6.3 Interface Management
Section 6.1 Technical Planning NPR 7120.5, NASA Space Flight Program and
NPR 7120.5, NASA Space Flight Program and Project Management Requirements
Section 6.4 Technical Risk Management
NPD 7120.6, Knowledge Policy on Programs and NPR 8000.4, Agency Risk Management Procedural
Projects Requirements
NPR 7123.1, NASA Systems Engineering Processes NASA/SP-2010-576, NASA Risk-Informed Decision
and Requirements Making Handbook
NASA-SP-2010-3403, NASA Schedule Management
Handbook
265

NASA/SP-2011-3421, Probabilistic Risk Assessment NPR 1600.1, NASA Security Program Procedural
Procedures Guide for NASA Managers and Requirements
Practitioners
NID 1600.55, Sensitive But Unclassified (SBU)
NASA/SP-2011-3422, NASA Risk Management Controlled Information
Handbook
NPR 7120.5, NASA Space Flight Program and
Code of Federal Regulations (CFR) Title 22 – Project Management Requirements
Foreign Relations, Parts 120-130 Department of
State: International Traffic in Arms Regulations NPR 7123.1, NASA Systems Engineering Processes
(ITAR) (22 CFR 120-130). Implements 22 and Requirements
U.S.C. 2778 of the Arms Export Control Act
(AECA) of 1976 and Executive Order 13637, NASA Form (NF) 1686, NASA Scientific and
“Administration of Reformed Export Controls,” Technical Document Availability Authorization
March 8, 2013 (DAA) for Administratively Controlled
Information.
Section 6.5 Configuration Management
NPR 7120.5, NASA Space Flight Program and Code of Federal Regulations (CFR) Title 22 –
Project Management Requirements Foreign Relations, Parts 120-130 Department of
State: International Traffic in Arms Regulations
NASA. Columbia Accident Investigation Board (ITAR) (22 CFR 120-130). Implements 22
(CAIB) Report, 6 volumes: Aug. 26, Oct. 2003. U.S.C. 2778 of the Arms Export Control Act
http://www.nasa.gov/columbia/caib/html/report.html (AECA) of 1976 and Executive Order 13637,
“Administration of Reformed Export Controls,”
NASA. NOAA N-Prime Mishap Investigation Final March 8, 2013
Report, Sept. 13, 2004 http://www.nasa.gov/pdf/
65776main_noaa_np_mishap.pdf The Invention Secrecy Act of 1951, 35 U.S.C.
§181–§188. Secrecy of Certain Inventions and
SAE International (SAE)/Electronic Industries Filing Applications in Foreign Country; §181 –
Alliance (EIA) 649B-2011, Configuration Secrecy of Certain Inventions and Withholding
Management Standard (Aerospace Sector) April 1, of Patent.
2011
Code of Federal Regulations (CFR) Title 37 –
American National Standards Institute (ANSI)/ Patents, Trademarks, and Copyrights; Part 5
Electronic Industries Alliance (EIA). ANSI/ Secrecy of Certain Inventions and Licenses
EIA-649, National Consensus Standard for to Export and File Applications in Foreign
Configuration Management, 1998–1999 Countries; Part 5.2 Secrecy Order. (37 CFR 5.2)
Section 6.6 Technical Data Management Section 6.7 Technical Assessment
NPR 1441.1, NASA Records Retention Schedules NPR 1080.1, Requirements for the Conduct of
NASA Research and Technology (R&T)
266

NPR 7120.5, NASA Space Flight Program and gov/web/se/tools/ and then NASA Tools &
Project Management Requirements Methods
NPR 7120.7, NASA Information Technology and American National Standards Institute/Electronic
Institutional Infrastructure Program and Project Industries Alliance (ANSI-EIA), Standard
Management Requirements 748-C Earned Value Management Systems.
March, 2013.
NPR 7120.8, NASA Research and Technology
Program and Project Management International Council on Systems Engineering
Requirements (INCOSE). INCOSE-TP-2003-020-01,
Technical Measurement, Version 1.0, 27
NPR 7123.1, NASA Systems Engineering Processes December 2005. Prepared by Garry J. Roedler
and Requirements (Lockheed Martin) and Cheryl Jones (U.S.
Army).
NPR 8705.4, Risk Classification for NASA Payloads
Section 6.8 Decision Analysis
NPR 8705.6, Safety and Mission Assurance (SMA) NPR 7120.5, NASA Space Flight Program and
Audits, Reviews, and Assessments Project Management Requirements
NPR 8715.3, NASA General Safety Program NPR 7123.1, NASA Systems Engineering Processes
Requirements and Requirements
NASA-HDBK-2203, NASA Software Engineering Brughelli, Kevin (Lockheed Martin), Deborah
Handbook. February 28, 2013 Carstens (Florida Institute of Technology),
and Tim Barth (Kennedy Space Center),
NASA/SP-2012-599, NASA’s Earned Value “Simulation Model Analysis Techniques,”
Management (EVM) Implementation Handbook Lockheed Martin presentation to KSC,
November 2003
NASA Federal Acquisition Regulation (FAR)
Supplement (NFS) 1834.201, Earned Value Saaty, Thomas L. The Analytic Hierarchy Process.
Management System Policy. New York: McGraw-Hill, 1980
NASA EVM website http://evm.nasa.gov/index.html Appendix B: Glossary
NPR 2210.1, Release of NASA Software
NASA Engineering Network (NEN) EVM
Community of Practice located at https://nen. NPD 7120.4, NASA Engineering and Program/
nasa.gov/web/pm/evm Project Management Policy
NASA Engineering Network (NEN) Systems NPR 7120.5, NASA Space Flight Program and
Engineering Community of Practice (SECoP) Project Management Requirements
under Tools and Methods at https://nen.nasa.
267

NPR 7123.1, NASA Systems Engineering Processes Long, James E. Relationships Between Common
and Requirements Graphical Representations in Systems Engineering.
Vienna, VA: Vitech Corporation, 2002
NPR 7150.2, NASA Software Engineering
Requirements Sage, Andrew, and William Rouse. The Handbook
of Systems Engineering and Management. New
NPR 8000.4, Agency Risk Management Procedural York: Wiley & Sons, 1999
Appendix G: Technology Assessment/
NPR 8705.2, Human-Rating Requirements for Insertion
Space Systems NPR 7120.5, NASA Space Flight Program and
NPR 8715.3, NASA General Safety Program
Requirements NPR 7123.1, NASA Systems Engineering Processes
and Requirements
International Organization for Standardization
(ISO). ISO/IEC/IEEE 42010:2011. Systems and Appendix H: Integration Plan Outline
Software Engineering – Architecture Description. Federal Highway Administration and CalTrans,
Geneva: International Organization for Systems Engineering Guidebook for ITS, Version
Standardization, 2011. (http://www.iso-architec- 2.0. Washington, DC: U.S. Department of
ture.org/ieee-1471/index.html) Transportation, 2007
Avizienis, A., J.C. Laprie, B. Randell, C. Landwehr, Appendix J: SEMP Content Outline
“Basic concepts and taxonomy of dependable NPR 7120.5, NASA Space Flight Program and
and secure computing,” IEEE Transactions on Project Management Requirements
Dependable and Secure Computing 1 (1), 11–33,
2004 NPR 7123.1, Systems Engineering Processes and
Appendix F: Functional, Timing, and State
Analysis Appendix K: Technical Plans
NASA Reference Publication 1370, Training NPR 7120.5, NASA Space Flight Program and
Manual for Elements of Interface Definition and Project Management Requirements
Control. 1997
Appendix M: CM Plan Outline
Defense Acquisition University. Systems Engineering SAE International (SAE)/Electronic Industries
Fundamentals Guide. Fort Belvoir, VA, 2001 Alliance (EIA) 649B-2011, Configuration
Management Standard (Aerospace Sector) April 1,
Buede, Dennis. The Engineering Design of Systems: 2011
Models and Methods. New York: Wiley & Sons,
2000
268

Appendix N: Guidance on Technical Peer NASA Langley Research Center (LaRC) Guidance
Reviews/Inspections on System and Software Metrics for Performance-
NPR 7123.1, Systems Engineering Processes and Based Contracting sites-e.larc.nasa.gov/sweng/
Requirements files/2013/05/Guidance_on_Metrics_for_PBC_
R1V01.doc
NPR 7150.2, NASA Software Engineering
Requirements Appendix R: HSI Plan Content Outline
NPR 7123.1, NASA Systems Engineering Processes
NASA Langley Research Center (LARC), and Requirements
Instructional Handbook for Formal Inspections.
http://sw-eng.larc.nasa.gov/files/2013/05/ NPR 8705.2, Human-Rating Requirements for
Instructional-Handbook-for-Formal-Inspections. Space Systems
pdf
NASA-STD-3001, Space Flight Human-System
Appendix P: SOW Review Checklist Standard, Volume 2: Human Factors,
NASA Langley Research Center (LaRC) Procedural Habitability, and Environmental Health,
Requirements (LPR) 5000.2 Procurement Section 3.5 [V2 3005], “Human-Centered
Initiator’s Guide Design Process.” February 10, 2015
269

Bibliography
The bibliography contains sources cited in sections of A
the document and additional sources for developing Adams, R. J., et al. Software Development Standard
the material in the document. for Space Systems, Aerospace Corporation Report
No. TOR-2004(3909)3537, Revision B. March
AIAA American Institute of Aeronautics and 11, 2005. Prepared for the U.S. Air Force.
Astronautics
ANSI American National Standards Institute
AIAA G-118-2006e, AIAA Guide for Managing the
ASME American Society of Mechanical Engineers
Use of Commercial Off the Shelf (COTS) Software
ASQ American Society for Quality
Components for Mission-Critical Systems, Reston,
CCSDS Consultative Committee for Space Data
Systems VA, 2006
CFR (U.S.) Code of Federal Regulations
COSPAR The Committee on Space Research AIAA S-120-2006, Mass Properties Control for Space
DOD (U.S.) Department of Defense Systems. Reston, VA, 2006
EIA Electronic Industries Alliance
GEIA Government Electronics Information AIAA S-122-2007, Electrical Power Systems for
Technology Association
Unmanned Spacecraft, Reston, VA, 2007
IEEE Institute of Electrical and Electronics
Engineers
ANSI/AIAA G-043-1992, Guide for the Preparation
INCOSE International Council on Systems
Engineering of Operational Concept Documents, Washington,
ISO International Organization for DC, 1992
Standardization
NIST National Institute of Standards and
ANSI/EIA-632, Processes for Engineering a System,
Technology
Arlington, VA, 1999
SAE Society of Automotive Engineers
TOR Technical Operating Report
U.S.C. United States Code ANSI/EIA-649, National Consensus Standard for
Configuration Management, 1998-1999
ANSI/GEIA-649, National Consensus Standard for
Configuration Management, National Defense
Industrial Association (NDIA), Arlington, VA
1998
ANSI/EIA-748-C Standard: Earned Value
Management Systems, March, 2013
270

ANSI/GEIA GEIA-859, Data Management, Blanchard, Benjamin S., System Engineering
National Defense Industrial Association Management. 4th Edition, Hoboken, NJ: John
(NDIA), Arlington, VA 2004 Wiley & Sons, Inc., 2008
ANSI/IEEE STD 1042. IEEE Guide to Software Blanchard, Benjamin S., and Wolter J. Fabrycky.
Configuration Management. Washington, DC, Systems Engineering and Analysis, 5th Edition
1987 Prentice Hall International Series in Industrial
& Systems Engineering; February 6, 2010
Architecture Analysis & Design Language (AADL):
https://wiki.sei.cmu.edu/aadl/index.php/Main_Page Brown, Barclay. “Model-based systems engineer-
ing: Revolution or Evolution,” IBM Software,
(The) Arms Export Control Act (AECA) of 1976, Thought Leadership White Paper, IBM
see 22 U.S.C. 2778 Rational, December 2011
ASME Y14.24, Types and Applications of Engineering Brughelli, Kevin (Lockheed Martin), Deborah
Drawings, New York, 1999 Carstens (Florida Institute of Technology),
and Tim Barth (Kennedy Space Center),
ASME Y14.100, Engineering Drawing Practices, New “Simulation Model Analysis Techniques,”
York, 2004 Lockheed Martin presentation to KSC,
November 2003
ASQ, Statistics Division, Statistical Engineering,
http://asq.org/statistics/quality-information/ Buede, Dennis. The Engineering Design of Systems:
statistical-engineering Models and Methods. New York: Wiley & Sons,
2000.
Avizienis, A., J.C. Laprie, B. Randell, C. Landwehr,
“Basic concepts and taxonomy of dependable Business Process Modeling Notation (BPMN) http://
and secure computing,” IEEE Transactions on www.bpmn.org/
Dependable and Secure Computing 1 (1), 11–33,
2004 C
CCSDS 311.0-M-1, Reference Architecture for
B Space Data Systems, Recommended Practice
Ball, Robert E. The Fundamentals of Aircraft Combat (Magenta), Sept 2008. http://public.ccsds.org/
Survivability Analysis and Design. 2nd Edition, publications/MagentaBooks.aspx
AIAA Education Series, 2003
CCSDS 901-0-G-1, Space Communications Cross
Bayer, T.J., M. Bennett, C. L. Delp, D. Dvorak, Support Architecture Description Document,
J. S. Jenkins, and S. Mandutianu. “Update: Informational Report (Green) Sept 2013. http://
Concept of Operations for Integrated Model- public.ccsds.org/publications/GreenBooks.aspx
Centric Engineering at JPL,” paper #1122, IEEE
Aerospace Conference 2011 Chapanis, A. “The Error-Provocative Situation:
A Central Measurement Problem in Human
271

Factors Engineering.” In The Measurement of CFR Title 22 – Foreign Relations, Parts 120-130
Safety Performance. Edited by W. E. Tarrants. Department of State: International Traffic in
New York: Garland STPM Press, 1980 Arms Regulations (ITAR) (22 CFR 120-130).
Implements 22 U.S.C. 2778 of the Arms Export
Chattopadhyay, Debarati, Adam M. Ross, and Control Act (AECA) of 1976 and Executive
Donna H. Rhodes, “A Method for Tradespace Order 13637, “Administration of Reformed
Exploration of Systems of Systems,” presen- Export Controls,” March 8, 2013
tation in Track 34-SSEE-3: Space Economic
Cost Modeling, AIAA Space 2009, September CFR Title 37 – Patents, Trademarks, and
15, 2009. © 2009 Massachusetts Institute Copyrights; Part 5 Secrecy of Certain
of Technology (MIT), SEARI: Systems Inventions and Licenses to Export and File
Engineering Advancement Research Initiative, Applications in Foreign Countries; Part 5.2
seari.mit.edu Secrecy Order. (37 CFR 5.2)
Chung, Seung H., Todd J. Bayer, Bjorn Cole, Brian CFR Title 40 – Protection of Environment, Part
Cooke, Frank Dekens, Christopher Delp, 1508.27 Council on Environmental Quality:
Doris Lam. “Model-Based Systems Engineering Terminology “significantly.” (40 CFR 1508.27)
Approach to Managing Mass Margin,” in
Proceedings of the 5th International Workshop CFR Title 48 – Federal Acquisition Regulation
on Systems & Concurrent Engineering for Space (FAR) System, Part 1214 NASA Acquisition
Applications (SECESA), Lisbon, Portugal, Planning: Acquisition of Commercial Items:
October, 2012 Space Flight. (48 CFR 1214)
Clark, J.O. “System of Systems Engineering CFR Title 48 – Federal Acquisition Regulation
and Family of Systems Engineering From (FAR) System, Part 46.103 Government
a Standards, V-Model, and Dual-V Model Contract Quality Assurance: Contracting office
Perspective,” 3rd Annual IEEE International responsibilities. (48 CFR 46.103)
Systems Conference, Vancouver, Canada, March
23–26, 2009 CFR Title 48 – Federal Acquisition Regulation
(FAR) System, Part 46.4 Government Contract
Clemen, R., and T. Reilly. Making Hard Decisions Quality Assurance (48 CFR 46.4)
with DecisionTools Suite. Pacific Grove, CA:
Duxbury Resource Center, 2002 CFR Title 48 – Federal Acquisition Regulation
(FAR) System, Part 46.407 Government
CFR, Title 14 – Aeronautics and Space, Part 1214 Contract Quality Assurance: Nonconforming
NASA Space Flight (14 CFR 1214) Supplies or Services (48 CFR 46.407)
CFR, Title 14 – Aeronautics and Space, Part 1216.3 COSPAR, Planetary Protection Policy. March
NASA Environmental Quality: Procedures for 24, 2005. http://w.astro.berkeley.edu/~kalas/
Implementing the National Environmental ethics/documents/environment/COSPAR%20
Policy Act (NEPA) (14 CFR 1216.3) Planetary%20Protection%20Policy.pdf
272

D DOD. MIL-STD-1472G, DOD Design Criteria
Deming, W. Edwards, see https://www.deming.org/ Standard: Human Engineering. Washington,
DC, January 11, 2012
Dezfuli, H. “Role of System Safety in Risk-informed
Decisionmaking.” In Proceedings, the NASA DOD. MIL-STD-1540D, Product Verification
Risk Management Conference 2005. Orlando, Requirements for Launch, Upper Stage, and Space
December 7, 2005 Vehicles. January 15, 1999
DOD Architecture Framework (DODAF) Version DOD. MIL-STD-46855A, Human Engineering
2.02 Change 1, January 2015 http://dodcio. Requirements for Military Systems, Equipment,
defense.gov/Library/DoDArchitectureFramework. and Facilities. May 24, 2011. Replacement for
aspx DOD HDBK 763 and DOD MIL-HDBK-
46855A, which have been cancelled.
DOD. Defense Acquisition Guidebook (DAG). 2014
DOD Office of the Under Secretary of Defense,
DOD Defense Acquisition University (DAU). Acquisition, Technology, & Logistics. SD-10.
Systems Engineering Fundamentals Guide. Fort Defense Standardization Program: Guide
Belvoir, VA, 2001 for Identification and Development of Metric
Standards. Washington, DC, April, 2010
DOD Defense Logistics Agency (DLA). Cataloging
Handbook, H4/H8 Series. Washington, DC, DOD Systems Management College. Systems
February 2003 Engineering Fundamentals. Defense Acquisition
University Press: Fort Belvoir, VA 22060-
DOD Defense Technical Information Center 5565, 2001 http://ocw.mit.edu/courses/
(DTIC). Directory of Design Support Methods aeronautics-and-astronautics/16-885j-air-
(DDSM). 2007. http://www.dtic.mil/dtic/tr/fulltext/ craft-systems-engineering-fall-2005/readings/sef-
u2/a437106.pdf guide_01_01.pdf
DOD MIL-HDBK-727 (Validation Notice 1). Duren, R. et al., “Systems Engineering for the
Military Handbook: Design Guidance for Kepler Mission: A Search for Terrestrial
Producibility, U.S. Army Research Laboratory, Planets,” IEEE Aerospace Conference, 2006
Weapons and Materials Research Directorate:
Adelphi,MD, 1990 E
Eggemeier, F. T., and G. F. Wilson. “Performance
DOD. MIL-HDBK-965. Acquisition Practices and Subjective Measures of Workload in
for Parts Management. Washington, DC, Multitask Environments.” In Multiple-Task
September 26, 1996. Notice 1: October 2000 Performance. Edited by D. Damos. London:
Taylor and Francis, 1991
DOD. MIL-STD-881C. Work Breakdown Structure
(WBS) for Defense Materiel Items. Washington, Endsley, M. R., and M. D. Rogers. “Situation
DC, October 3, 2011 Awareness Information Requirements
273

Analysis for En Route Air Traffic Control.” In (HFDS). Washington, DC, May 2003.
Proceedings of the Human Factors and Ergonomics Updated: May 03, 2012. hf.tc.faa.gov/hfds
Society 38th Annual Meeting. Santa Monica:
Human Factors and Ergonomics Society, 1994 Federal Highway Administration, and CalTrans.
Systems Engineering Guidebook for ITS, Version
Eslinger, Suellen. Software Acquisition Best Practices 2.0. Washington, DC: U.S. Department of
for the Early Acquisition Phases. El Segundo, CA: Transportation, 2007
The Aerospace Corporation, 2004
Friedenthal, Sanford, Alan Moore, and Rick Steiner.
Estefan, Jeff, Survey of Model-Based Systems A Practical Guide to SysML: Systems Modeling
Engineering (MBSE) Methodologies, Rev B, Language, Morgan Kaufmann Publishers, Inc.,
Section 3.2. NASA Jet Propulsion Laboratory July 2008
(JPL), June 10, 2008. The document was orig-
inally authored as an internal JPL report, and Fuld, R. B. “The Fiction of Function Allocation.”
then modified for public release and submitted Ergonomics in Design (January 1993): 20–24
to INCOSE to support the INCOSE MBSE
Initiative. G
Garlan, D., W. Reinholtz, B. Schmerl, N.
Executive Order (EO) 12114, Environmental Effects Sherman, T. Tseng. “Bridging the Gap
Abroad of Major Federal Actions. January 4, between Systems Design and Space Systems
1979. Software,” Proceedings of the 29th IEEE/NASA
Software Engineering Workshop, 6-7 April 2005,
Executive Order (EO) 12770, Metric Usage in Greenbelt, MD, USA
Federal Government Programs, July 25, 1991.
Glass, J. T., V. Zaloom, and D. Gates. “A Micro-
Executive Order (EO) 13637, Administration of Computer-Aided Link Analysis Tool.”
Reformed Export Controls, March 8, 2013. Computers in Industry 16, (1991): 179–87
Extensible Markup Language (XML) http://www. Gopher, D., and E. Donchin. “Workload: An
w3.org/TR/REC-xml/ Examination of the Concept.” In Handbook
of Perception and Human Performance: Vol. II.
Extensible Markup Language (XML) Metadata Cognitive Processes and Performance. Edited by
Interchange (XMI) http://www.omg.org/spec/XMI/ K. R. Boff, L. Kaufman, and J. P. Thomas. New
York: John Wiley & Sons, 1986
F
Federal Acquisition Regulation (FAR). See: Code of Griffin, Michael D., NASA Administrator.
Federal Regulations (CFR), Title 48. “System Engineering and the Two Cultures
of Engineering.” Boeing Lecture, Purdue
Federal Aviation Administration (FAA), University, March 28, 2007
HF-STD-001, Human Factors Design Standard
274

H IEEE STD 1220-2005. IEEE Standard for
Hart, S. G., and C. D. Wickens. “Workload Application and Management of the Systems
Assessment and Prediction.” In MANPRINT: Engineering Process, Washington, DC, 2005
An Approach to Systems Integration. Edited by H.
R. Booher. New York: Van Nostrand Reinhold, IEEE Standard12207.1, EIA Guide for Information
1990 Technology Software Life Cycle Processes—Life
Cycle Data, Washington, DC, 1997
Hoerl, R.W. and R.S. Snee, Statistical Thinking –
Improving Business Performance, John Wiley & INCOSE. Systems Engineering Handbook, Version
Sons. 2012 3.2.2. Seattle, 2011
Hoffmann, Hans-Peter, “Harmony-SE/SysML INCOSE-TP-2003-002-04, Systems Engineering
Deskbook: Model-Based Systems Engineering Handbook: A Guide for System Life Cycle Processes
with Rhapsody,” Rev. 1.51, Telelogic/I-Logix and Activities, Version 4, Edited by Walden,
white paper, Telelogic AB, May 24, 2006 David D., et al., 2015
Hofmann, Hubert F., Kathryn M. Dodson, Gowri INCOSE-TP-2003-020-01, Technical Measurement,
S. Ramani, and Deborah K. Yedlin. Adapting Version 1.0, 27 December 2005. Prepared by
CMMI® for Acquisition Organizations: A Garry J. Roedler (Lockheed Martin) and Cheryl
Preliminary Report, CMU/SEI-2006-SR-005. Jones (U.S. Army).
Pittsburgh: Software Engineering Institute,
Carnegie Mellon University, 2006, pp. 338–40 INCOSE-TP-2004-004-02, Systems Engineering
Vision 2020, Version 2.03, September 2007,
Huey, B. M., and C. D. Wickens, eds. Workload http://www.incose.org/ProductsPubs/pdf/
Transition. Washington, DC: National Academy SEVision2020_20071003_v2_03.pdf
Press, 1993
INCOSE-TP-2005-001-03, Systems Engineering
I Leading Indicators Guide, Version 2.0, January
IEEE STD 610.12-1990. IEEE Standard Glossary 29, 2010; available at http://seari.mit.edu/docu-
of Software Engineering Terminology. 1999, ments/SELI-Guide-Rev2.pdf. Edited by Garry J.
superceded by ISO/IEC/IEEE 24765:2010, Roedler and Howard Schimmoller (Lockheed
Systems and Software Engineering – Vocabulary. Martin), Cheryl Jones (U.S. Army), and
Washington, DC, 2010 Donna H. Rhodes (Massachusetts Institute of
Technology)
IEEE STD 828. IEEE Standard for Software
Configuration Management Plans. Washington, ISO 9000:2015, Quality management systems –
DC, 1998 Fundamentals and vocabulary. Geneva:
International Organization for Standardization,
IEEE STD 1076-2008 IEEE Standard VHDL 2015
Language Reference Manual, 03 February 2009
275

ISO 9001:2015 Quality Management Systems ISO/TR 15846. Information Technology—Software
(QMS). Geneva: International Organization for Life Cycle Processes Configuration Management,
Standardization, September 2015 Geneva: International Organization for
Standardization, 1998
ISO 9100/AS9100, Quality Systems Aerospace—
Model for Quality Assurance in Design, ISO/IEC TR 19760:2003. Systems Engineering—A
Development, Production, Installation, and Guide for the Application of ISO/IEC 15288.
Servicing. Geneva: International Organization Geneva: International Organization for
for Standardization, 1999 Standardization, 2003
ISO 10007: 1995(E). Quality Management— ISO/IEC/IEEE 24765:2010, Systems and
Guidelines for Configuration Management, Software Engineering – Vocabulary. Geneva:
Geneva: International Organization for International Organization for Standardization,
Standardization, 1995 2010
ISO 10303-AP233, Application Protocol (AP) for ISO/IEC/IEEE 42010:2011. Systems and Software
Systems Engineering Data Exchange (AP-233) Engineering—Architecture Description.
Working Draft 2 published July 2006 Geneva: International Organization for
Standardization, 2011 http://www.iso-architec-
ISO/TS 10303-433:2011 Industrial automation ture.org/ieee-1471/index.html
systems and integration – Product data representa-
tion and exchange – Part 433: Application mod- (The) Invention Secrecy Act of 1951, see 35 U.S.C.
ule: AP233 systems engineering. ISO: Geneva, §181–§188. Secrecy of Certain Inventions and
2011 Filing Applications in Foreign Country; §181 –
Secrecy of Certain Inventions and Withholding
ISO/IEC 10746-1 to 10746-4, ITU-T Specifications of Patent
X.901 to x.904, Reference Model of Open
distributed Processing (RM-ODP), Geneva: J
International Organization for Standardization, Joint (cost and schedule) Confidence Level (JCL).
1998. http://www.rm-odp.net Frequently asked questions (FAQs) can be found
at: http://www.nasa.gov/pdf/394931main_JCL_
ISO 13374-1, Condition monitoring and diagnostics of FAQ_10_12_09.pdf
machines—Data processing, communication and
presentation – Part 1: General guidelines. Geneva: Jennions, Ian K. editor. Integrated Vehicle Health
International Organization for Standardization, Management (IVHM): Perspectives on an
2002 Emerging Field. SAE International, Warrendale
PA (IVHM Book) September 27, 2011
ISO/IEC 15288:2002. Systems Engineering—System
Life Cycle Processes. Geneva: International Jennions, Ian K. editor. Integrated Vehicle Health
Organization for Standardization, 2002 Management (IVHM): Business Case Theory and
276

Practice. SAE International, Warrendale PA Value Tradeoffs. Cambridge, UK: Cambridge
(IVHM Book) November 12, 2012 University Press, 1993
Jennions, Ian K. editor. Integrated Vehicle Health Kirwin, B., and L. K. Ainsworth. A Guide to Task
Management (IVHM): The Technology. SAE Analysis. London: Taylor and Francis, 1992
International, Warrendale PA (IVHM Book)
September 5, 2013 Kluger, Jeffrey with Dan Cray, “Management
Tips from the Real Rocket Scientists,” Time
Johnson, Stephen B. et al., editors. System Health Magazine, November 2005
Management with Aerospace Applications. John
Wiley & Sons, Ltd, West Sussex, UK, 2011 Knowledge Based Systems, Inc. (KBSI), Integration
Definition for functional modeling (IDEF0) ISF0
Jones, E. R., R. T. Hennessy, and S. Deutsch, Function Modeling Method, found at http://www.
eds. Human Factors Aspects of Simulation. idef.com/idef0.htm
Washington, DC: National Academy Press,
1985 Kruchten, Philippe B. The Rational Unified Process:
An Introduction, Third Edition, Addison-Wesley
K Professional: Reading, MA, 2003
Kaplan, S., and B. John Garrick. “On the
Quantitative Definition of Risk.” Risk Analysis Kruchten, Philippe B. “A 4+1 view model of soft-
1(1). 1981 ware architecture,” IEEE Software Magazine
12(6) (November 1995), 42–50
Karpati, G., Martin, J., Steiner, M., Reinhardt,
K., “The Integrated Mission Design Center Kurke, M. I. “Operational Sequence Diagrams in
(IMDC) at NASA Goddard Space Flight System Design.” Human Factors 3: 66–73. 1961
Center,” IEEE Aerospace Conference 2003
Proceedings, Volume 8, Page(s): 8_3657–8_3667, L
2003 Larson, Wiley J.et al.. Applied Space Systems
Engineering: A Practical Approach to Achieving
Keeney, Ralph L. Value-Focused Thinking: A Path Technical Baselines. 2nd Edition, Boston,
to Creative Decisionmaking. Cambridge, MA: MA: McGraw-Hill Learning Solutions, CEI
Harvard University Press, 1992 Publications, 2009
Keeney, Ralph L., and Timothy L. McDaniels. “A Long, James E., Relationships Between Common
Framework to Guide Thinking and Analysis Graphical Representations in Systems Engineering.
Regarding Climate Change Policies.” Risk Vienna, VA: Vitech Corporation, 2002
Analysis 21(6): 989–1000. 2001
Long, James E., “Systems Engineering (SE) 101,”
Keeney, Ralph L., and Howard Raiffa. Decisions CORE®: Product & Process Engineering Solutions,
with Multiple Objectives: Preferences and Vitech training materials. Vienna, VA: Vitech
Corporation, 2000
277

M Meister, David, Human Factors: Theory and Practice.
Maier, M.W. “Architecting Principles for Systems-of- New York: John Wiley & Sons, 1971
Systems,” Systems Engineering 1(1998), 267-284,
John Wiley & Sons, Inc. (The) Metric Conversion Act of 1975 (Public Law
94-168) amended by the Omnibus Trade and
Maier, M.W., D. Emery, and R. Hillard, “ANSI/ Competitiveness Act of 1988 (Public Law 100-
IEEE 1471 and Systems Engineering,” 418), the Savings in Construction Act of 1996
Systems Engineering 7 (2004), 257–270, Wiley (Public Law 104-289), and the Department of
InterScience, http://www.interscience.wiley.com Energy High-End Computing Revitalization
Act of 2004 (Public Law 108-423). See 15
Maier, M.W. “System and Software Architecture U.S.C. §205a et seq.
Reconciliation,” Systems Engineering 9 (2006),
146–159, Wiley InterScience, http://www.inter- Miao, Y., and J. M. Haake. “Supporting Concurrent
science.wiley.com Design by Integrating Information Sharing and
Activity Synchronization.” In Proceedings of the
Maier, M.W., and E. Rechtin, The Art of Systems 5th ISPE International Conference on Concurrent
Architecting, 3rd Edition, CRC Press, Boca Engineering Research and Applications (CE98).
Raton, FL, 2009 Tokyo, 1998, pp. 165–74
Martin, James N., Processes for Engineering a System: The Mitre Corporation, Common Risks and Risk
An Overview of the ANSI/GEIA EIA-632 Mitigation Actions for a COTS-based System.
Standard and Its Heritage. New York: Wiley & McLean, VA. http://www2.mitre.org/…/files/
Sons, 2000 CommonRisksCOTS.doc (no date)
Martin, James N., Systems Engineering Guidebook: A MODAF http://www.modaf.com/
Process for Developing Systems and Products. Boca
Raton: CRC Press, 1996. Moeller, Robert C., Chester Borden, Thomas
Spilker, William Smythe, Robert Lock ,
Mathworks: Matlab http://www.mathworks.com/ “Space Missions Trade Space Generation
and Assessment using the JPL Rapid Mission
McGuire, M., Oleson, S., Babula, M., and Sarver- Architecture (RMA) Team Approach,” IEEE
Verhey, T., “Concurrent Mission and Systems Aerospace Conference, Big Sky, Montana, March
Design at NASA Glenn Research Center: The 2011
origins of the COMPASS Team,” AIAA Space
2011 Proceedings, September 27-29, 2011, Long Morgan, M. Granger, and M. Henrion, Uncertainty:
Beach, CA A Guide to Dealing with Uncertainty in
Quantitative Risk and Policy Analysis.
Meister, David, Behavioral Analysis and Measurement Cambridge, UK: Cambridge University Press,
Methods. New York: John Wiley & Sons, 1985 1990
278

M. Moshir, et al., “Systems engineering and appli- Investigation Board Report, January 30, 2004.
cation of system performance modeling in SIM Mr. Al Diaz, Director, Goddard Space Flight
Lite mission,” Proceedings. SPIE 7734, 2010 Center, and team
Mulqueen, J.; R. Hopkins; D. Jones, “The MSFC NASA JPL D-71990, Europa Study 2012 Full Report.
Collaborative Engineering Process for May 1 2012, publicly available here: http://
Preliminary Design and Concept Definition solarsystem.nasa.gov/europa/2012study.cfm
Studies.” 2012 http://ntrs.nasa.gov/archive/nasa/
casi.ntrs.nasa.gov/20120001572.pdf NASA Office of Inspector General. Final
Memorandum on NASA’s Acquisition Approach
NASA Publications Regarding Requirements for Certain Software
Engineering Tools to Support NASA Programs,
NASA Federal Acquisition Regulation (FAR) Assignment No. S06012. Washington, DC,
Supplement (NFS) 1834.201, Earned Value 2006
Management System Policy
NASA Office of Inspector General. Performance-
NASA Form (NF) 1686, NASA Scientific and Based Contracting https://oig.nasa.gov/august/
Technical Document Availability Authorization report/FY06/s06012
(DAA) for Administratively Controlled
Information Specialty Web Sites
NASA Engineering Network (NEN) Systems
Reports Engineering Community of Practice (SECoP)
NASA Chief Engineer and the NASA Integrated located at https://nen.nasa.gov/web/se
Action Team (NIAT) report, “Enhancing
Mission Success—A Framework for the Future,” NASA Engineering Network (NEN) Systems
December 21, 2000. Authors: McBrayer, Robert Engineering Community of Practice (SECoP)
O and Thomas, Dale, NASA Marshall Space under Tools and Methods at https://nen.nasa.
Flight Center, Huntsville, AL United States gov/web/se/tools/ and then NASA Tools &
Methods
NASA. Columbia Accident Investigation Board
(CAIB) Report, 6 volumes: Aug. 26, Oct. 2003. NASA Engineering Network (NEN) V&V
http://www.nasa.gov/columbia/caib/html/report. Community of Practice, located at https://nen.
html nasa.gov/web/se
NASA. NOAA N-Prime Mishap Investigation Final NASA Engineering Network (NEN) EVM
Report, Sept. 13, 2004. http://www.nasa.gov/pdf/ Community of Practice, https://nen.nasa.gov/
65776main_noaa_np_mishap.pdf web/pm/evm
NASA. Diaz Report, A Renewed Commitment to NASA EVM website http://evm.nasa.gov/index.html
Excellence: An Assessment of the NASA Agency-
wide Applicability of the Columbia Accident
279

NASA Procurement Library found at http://www. NASA PD-EC-1243, Preferred Reliability Practices
hq.nasa.gov/office/procurement/ for Fault Protection, October 1995
Conference Publications NASA-CR-192656, Contractor Report: Research
NASA 2011 Statistical Engineering Symposium, and technology goals and objectives for Integrated
Proceedings. http://engineering.larc.nasa.gov/2011_ Vehicle Health Management (IVHM). October
NASA_Statistical_Engineering_Symposium.html 10, 1992
Aerospace Conference, 2007 IEEE Big Sky, MT 3–10 NASA Jet Propulsion Laboratory (JPL), JPL-
March 2007. NASA/Aerospace Corp. paper: D-17868 (REV.1), JPL Guideline: Design,
“Using Historical NASA Cost and Schedule Verification/Validation and Operations Principles
Growth to Set Future Program and Project for Flight Systems. February 16, 2001
Reserve Guidelines,” by Emmons, D. L., R.E.
Bitten, and C.W. Freaner. IEEE Conference NASA Lyndon B. Johnson Space Center (JSC-
Publication pages: 1–16, 2008. Also presented 65995), Commercial Human Systems Integration
at the NASA Cost Symposium, Denver CO, Processes (CHSIP), May 2011
July 17–19, 2007
NASA/TP-2014-218556, Technical Publication:
NASA Cost Symposium 2014, NASA “Mass Growth Human Integration Design Processes (HIDP).
Analysis: Spacecraft & Subsystems.” LaRC, NASA ISS Program, Lyndon B. Johnson Space
August 14th, 2014. Presenter: Vincent Larouche Center, Houston TX, September 2014. http://
– Tecolote Research, also James K. Johnson, ston.jsc.nasa.gov/collections/TRS/_techrep/
NASA HQ Study Point of Contact TP-2014-218556.pdf
Planetary Science Subcommittee, NASA Advisory NASA Lyndon B. Johnson Space Center (JSC-
Council, 23 June, 2008, NASA GSFC. NASA/ 60576), National Space Transportation System
Aerospace Corp. presentation; “An Assessment (NSTS), Space Shuttle Program, Transition
of the Inherent Optimism in Early Conceptual Management Plan, May 9, 2007
Designs and its Effect on Cost and Schedule
Growth,” by Freaner, Claude, Bob Bitten, Dave NASA Langley Research Center (LARC) Guidance
Bearden, and Debra Emmons on System and Software Metrics for Performance-
Based Contracting. 2013 sites-e.larc.nasa.gov/
Technical Documents sweng/files/2013/05/Guidance_on_Metrics_for_
NASA Office of Chief Information Officer (OCIO). PBC_R1V01.doc
Information Technology Systems Engineering
Handbook Version 2.0 NASA Langley Research Center (LARC),
Instructional Handbook for Formal Inspections.
NASA Science Mission Directorate, Risk 2013 http://sw-eng.larc.nasa.gov/files/2013/05/
Communication Plan for Planetary and Deep Instructional-Handbook-for-Formal-Inspections.
Space Missions, 1999 pdf
280

NASA/TM-2008-215126/Volume II (NESC- NASA/SP-2010-3407, Human Integration Design
RP-06-108/05-173-E/Part 2), Technical Handbook (HIDH)
Memorandum: Design Development Test and
Evaluation (DDT&E) Considerations for Safe and NASA/SP-2011-3421, Probabilistic Risk Assessment
Reliable Human-Rated Spacecraft Systems. April Procedures Guide for NASA Managers and
2008.Volume II: Technical Consultation Report. Practitioners
James Miller, Jay Leggett, and Julie Kramer-
White, NASA Langley Research Center, NASA/SP-2011-3422, NASA Risk Management
Hampton VA, June 14, 2007 Handbook
NASA Reference Publication 1370. Training NASA/SP-2013-3704, Earned Value Management
Manual for Elements of Interface Definition and (EVM) System Description
Control. Vincent R. Lalli, Robert E. Kastner,
and Henry N. Hartt. NASA Lewis Research NASA/SP-2014-3705, NASA Space Flight Program
Center, Cleveland OH, January 1997 and Project Management Handbook
NASA. Systems Engineering Leading Indicators NASA/SP-2015-3709, Human Systems Integration
Guide, http://seari.mit.edu/ Practitioners Guide
NASA Cost Estimating Handbook (CEH), Version 4, Handbooks and Standards
February 2015 NASA-HDBK-1002, Fault Management (FM)
Handbook, Draft 2, April 2012
NASA Financial Management Requirements (FMR)
Volume 4 NASA-HDBK-2203, NASA Software Engineering
Handbook, February 28, 2013
Special Publications
NASA/SP-2010-576 NASA Risk-Informed Decision NASA Safety Standard (NSS) 1740.14, Guidelines
Making Handbook and Assessment Procedures for Limiting Orbital
Debris. Washington, DC, 1995 http://www.
NASA/SP-2012-599, NASA’s Earned Value hq.nasa.gov/office/codeq/doctree/174014.htm
Management (EVM) Implementation Handbook NASA-STD 8719.14 should be used in place
of NSS 1740.14 to implement NPR 8715.6. See
NASA/SP-2010-3403, NASA Schedule Management NPR 8715.6 for restrictions on the use of NSS
Handbook 1740.14.
NASA/SP-2010-3404, NASA Work Breakdown NASA GSFC-STD-1000, Rules for the Design,
Structure Handbook Development, Verification, and Operation of
Flight Systems. NASA Goddard Space Flight
NASA/SP-2010-3406, Integrated Baseline Review Center, February 8, 2013
(IBR) Handbook
281

NASA-STD-3001, Space Flight Human System NPD 2820.1, NASA Software Policy
Standard. Volume 1: Crew Health. Rev. A, July
30, 2014 NPD 7120.4, NASA Engineering and Program/
Project Management Policy
NASA-STD-3001, Space Flight Human System
Standard. Volume 2: Human Factors, NPD 7120.6, Knowledge Policy on Programs and
Habitability, and Environmental Health. Rev. A, Projects
February 10, 2015
NPD 8010.2, Use of the SI (Metric) System of
NASA GSFC-STD-7000, Goddard Technical Measurement in NASA Programs
Standard: General Environmental Verification
Standard (GEVS) for GSFC Flight Programs and NPD 8010.3, Notification of Intent to
Projects. Goddard Space Flight Center, April Decommission or Terminate Operating Space
2005 Systems and Terminate Missions
NASA KSC-NE-9439 Kennedy Space Center Design NPD 8020.7, Biological Contamination Control for
Engineering Handbook, Best Practices for Design Outbound and Inbound Planetary Spacecraft
and Development of Ground Systems. Kennedy
Space Center, November 20 2009 NPD 8730.5, NASA Quality Assurance Program
Policy
NASA-STD-7009, Standard for Models and
Simulations. Washington, DC, October 18, Procedural Requirements
2013 NPR 1080.1, Requirements for the Conduct of
NASA Research and Technology (R&T)
NASA-STD-8719.13, Software Safety Standard, Rev
C. Washington, DC, May 7, 2013 NPR 1441.1, NASA Records Retention Schedules
NASA-STD-8719.14, Handbook for Limiting Orbital NPR 1600.1, NASA Security Program Procedural
Debris. Rev A with Change 1. December 8, 2011 Requirements
NASA-STD-8729.1, Planning, Developing, and NPR 2210.1, Release of NASA Software
Maintaining an Effective Reliability and
Maintainability (R&M) Program. Washington, NPR 2810.1, Security of Information Technology
DC, December 1, 1998
LPR 5000.2, Procurement Initiator’s Guide. NASA
Policy Directives Langley Research Center (LARC)
NPD 1001.0, 2014 NASA Strategic Plan
JPR 7120.3, Project Management: Systems
NID 1600.55, Sensitive But Unclassified (SBU) Engineering & Project Control Processes and
Controlled Information Requirements. NASA Lyndon B. Johnson Space
Center (JSC)
282

NPR 7120.5, NASA Space Flight Program NPR 8705.2, Human-Rating Requirements for
and Project Management Processes and Space Systems
NPR 8705.3, Probabilistic Risk Assessment
NPR 7120.7, NASA Information Technology and Procedures Guide for NASA Managers and
Institutional Infrastructure Program and Project Practitioners
Management Requirements
NPR 8705.4, Risk Classification for NASA Payloads
NPR 7120.8, NASA Research and Technology
Program and Project Management NPR 8705.5, Probabilistic Risk Assessment (PRA)
Requirements Procedures for NASA Programs and Projects
NPR 7120.10, Technical Standards for NASA NPR 8705.6, Safety and Mission Assurance (SMA)
Programs and Projects Audits, Reviews, and Assessments
NPR 7120.11, NASA Health and Medical Technical NPR 8710.1, Emergency Preparedness Program
Authority (HMTA) Implementation
NPR 8715.2, NASA Emergency Preparedness Plan
NPR 7123.1, Systems Engineering Processes and Procedural Requirements
NPR 8715.3, NASA General Safety Program
NPR 7150.2, NASA Software Engineering Requirements
NPR 8715.6, NASA Procedural Requirements for
NPR 8000.4, Risk Management Procedural Limiting Orbital Debris
NPR 8735.2, Management of Government Quality
NPI 8020.7, NASA Policy on Planetary Protection Assurance Functions for NASA Contracts
Requirements for Human Extraterrestrial
Missions NPR 8900.1, NASA Health and Medical
Requirements for Human Space Exploration
NPR 8020.12, Planetary Protection Provisions for
Robotic Extraterrestrial Missions Work Instructions
MSFC NASA MWI 8060.1, Off-the-Shelf Hard-
APR 8070.2, EMI/EMC Class D Design and ware Utilization in Flight Hardware Develop-
Environmental Test Requirements. NASA Ames ment. NASA Marshall Space Flight Center.
Research Center (ARC)
JSC Work Instruction EA-WI-016, Off-the-Shelf
NPR 8580.1, Implementing the National Hardware Utilization in Flight Hardware
Environmental Policy Act and Executive Order Development. NASA Lyndon B. Johnson Space
12114 Center.
283

Acquisition Documents O
NASA. The SEB Source Evaluation Process. Oberto, R.E., Nilsen, E., Cohen, R., Wheeler, R.,
Washington, DC, 2001 DeFlorio, P., and Borden, C., “The NASA
Exploration Design Team; Blueprint for a
NASA. Solicitation to Contract Award. Washington, New Design Paradigm”, 2005 IEEE Aerospace
DC, NASA Procurement Library, 2007 Conference, Big Sky, Montana, March 2005
NASA. Statement of Work Checklist. Washington, Object Constraint Language (OCL) http://www.omg.
DC. See: Appendix P in this handbook. org/spec/OCL/
N Office of Management and Budget (OMB) Circular
(The) National Environmental Policy Act of 1969 A-94, Guidelines and Discount Rates for Benefit-
(NEPA). See 42 U.S.C. 4321-4347. https://ceq. Cost Analysis of Federal Programs, October 29,
doe.gov/welcome.html 1992
National Research Council (NRC) of the National Oliver, D., T. Kelliher, and J. Keegan, Engineering
Academy of Sciences (NAS), The Planetary Complex Systems with Models and Objects, New
Decadal Survey 2013–2022, Vision and Voyagers York, NY, USA: McGraw-Hill 1997
for Planetary Science in the Decade 2013–2022,
The National Academies Press: Washington, OOSEM Working Group, Object-Oriented Systems
D.C., 2011. http://www.nap.edu Engineering Method (OOSEM) Tutorial, Version
03.00, Lockheed Martin Corporation and
NIST Special Publication 330: The International INCOSE, October 2008
System of Units (SI) Barry N. Taylor and Ambler
Thompson, Editors, March 2008. The United OWL, Web Ontology Language (OWL) http://www.
States version of the English text of the eighth w3.org/2001/sw/wiki/OWL
edition (2006) of the International Bureau of
Weights and Measures publication Le Système P
International d’ Unités (SI) Paredis, C., Y. Bernard, R. Burkhart, H.P. Koning,
S. Friedenthal, P. Fritzon, N.F. Rouquette,
NIST Special Publication 811: NIST Guide for the W. Schamai. “Systems Modeling Language
Use of the International System of Units (SI) A. (SysML)-Modelica Transformation.” INCOSE
Thompson and B. N. Taylor, Editors. Created 2010
July 2, 2009; Last updated January 28, 2016
Pennell, J. and Winner, R., “Concurrent
NIST, Federal Information Processing Standard Engineering: Practices and Prospects,” Global
Publication (FIPS PUB) 199, Standards for Telecommunications Conference, GLOBECOM
Security Categorization of Federal Information ‘89, 1989
and Information Systems, February 2004
Presidential Directive/National Security Council
Memorandum No. 25 (PD/NSC-25), “Scientific
284

or Technological Experiments with Possible SAE Standard AS5506B, Architecture Analysis &
Large-Scale Adverse Environmental Effects Design Language (AADL), SAE International,
and Launch of Nuclear Systems into Space,” as September 10, 2012
amended May 8, 1996
SAE International and the European Association of
Presidential Policy Directive PPD-4 (2010), National Aerospace Industries (EAAI) AS9100C, Quality
Space Policy Management Systems (QMS): Requirements for
Aviation, Space, and Defense Organizations
Presidential Policy Directive PPD-21 (2013), Critical Revision C, January 15, 2009
Infrastructure Security and Resilience
SAE International/Electronic Industries Alliance
Price, H. E. “The Allocation of Functions in (EIA) 649B-2011, Configuration Management
Systems.” Human Factors 27: 33–45. 1985 Standard (Aerospace Sector), April 1, 2011
The Project Management Institute® (PMI). Practice Sage, Andrew, and William Rouse. The Handbook
Standards for Work Breakdown Structures. of Systems Engineering and Management, New
Newtown Square, PA, 2001 York: Wiley & Sons, 1999
Q Shafer, J. B. “Practical Workload Assessment in the
Query View Transformation (QVT) http://www.omg. Development Process.” In Proceedings of the
org/spec/QVT/1.0/ Human Factors Society 31st Annual Meeting,
Santa Monica: Human Factors Society, 1987
R
Rasmussen, Robert. “Session 1: Overview of Shames, P., and J. Skipper. “Toward a Framework
State Analysis,” (internal document), State for Modeling Space Systems Architectures,”
Analysis Lite Course, Jet Propulsion Laboratory, SpaceOps 2006 Conference, AIAA 2006-5581,
California Institute of Technology, Pasadena, 2006
CA, 2005
Shaprio, J., “George H. Heilmeier,” IEEE Spectrum,
R. Rasmussen, B. Muirhead, Abridged Edition: 31(6), 1994, pg. 56–59 http://ieeexplore.ieee.org/
A Case for Model-Based Architecting in NASA, iel3/6/7047/00284787.pdf?arnumber=284787
California Institute of Technology, August 2012
Software Engineering Institute (SEI). A Framework
Rechtin, Eberhardt. Systems Architecting of for Software Product Line Practice, Version 5.0.
Organizations: Why Eagles Can’t Swim. Boca Carnegie Mellon University, http://www.sei.cmu.
Raton: CRC Press, 2000 edu/productlines/frame_report/arch_def.htm
S Stamelatos, M., H. Dezfuli, and G. Apostolakis.
Saaty, Thomas L. The Analytic Hierarchy Process. “A Proposed Risk-Informed Decision making
New York: McGraw-Hill, 1980 Framework for NASA.” In Proceedings of the 8th
International Conference on Probabilistic Safety
285

Assessment and Management. New Orleans, LA, Performance-Based Regulation,Washington, DC,
May 14–18, 2006 1998
Stern, Paul C., and Harvey V. Fineberg, eds. U.S. Nuclear Regulatory Commission. NUREG-
Understanding Risk: Informing Decisions in a 0700, Human-System Interface Design Review
Democratic Society. Washington, DC: National Guidelines, Rev.2. Washington, DC, Office of
Academies Press, 1996 Nuclear Regulatory Research, 2002
Systems Modeling Language (SysML) http://www. United Nations, Office for Outer Space Affairs.
omgsysml.org/ Treaty of Principles Governing the Activities of
States in the Exploration and Use of Outer Space,
T Including the Moon and Other Celestial Bodies.
Taylor, Barry. Guide for the Use of the International Known as the “Outer Space Treaty of 1967”
System of Units (SI), Special Publication 811.
Gaithersburg, MD: NIST, Physics Laboratory, W
2007 Wall, S., “Use of Concurrent Engineering in Space
Mission Design,” Proceedings of EuSEC 2000,
U Munich, Germany, September 2000
Unified Modeling Language (UML) http://www.uml.
org/ Warfield, K., “Addressing Concept Maturity in the
Early Formulation of Unmanned Spacecraft,”
UPDM: Unified Profile for the (US) Department Proceedings of the 4th International Workshop
of Defense Architecture Framework (DoDAF) on System and Concurrent Engineering for Space
and the (UK) Ministry Of Defense Architecture Applications, October 13–15, 2010, Lausanne,
Framework (MODAF) http://www.omg.org/spec/ Switzerland
UPDM/
Web Ontology Language (OWL) http://www.
U.S. Air Force. SMC Systems Engineering Primer w3.org/2001/sw/wiki/OWL
and Handbook, 3rd ed. Los Angeles: Space and
Missile Systems Center, 2005 Wessen, Randii R., Chester Borden, John Ziemer,
and Johnny Kwok. “Space Mission Concept
U. S. Chemical Safety Board (CSB) case study Development Using Concept Maturity Levels,”
reports on mishaps found at: http://www.csb.gov/ Conference paper presented at the American
Institute of Aeronautics and Astronautics
U.S. Navy. Naval Air Systems Command, Systems (AIAA) Space 2013 Conference and Exposition;
Engineering Guide: 2003 (based on require- September 10–12, 2013; San Diego, CA.
ments of ANSI/EIA 632:1998). Patuxent River, Published in the AIAA Space 2013 Proceedings
MD, 2003
Winner, R., Pennell, J., Bertrand, H., and
U.S. Nuclear Regulatory Commission. SECY- Slusarczuk, M., The Role Of Concurrent
98-144, White Paper on Risk-Informed and Engineering In Weapons System Acquisition,
286

Institute of Defense Analyses (IDA) Report XML: Extensible Markup Language (XML) http://
R-338, Dec 1988 www.w3.org/TR/REC-xml/
Wolfram, Mathematica http://www.wolfram.com/ Z
mathematica/ Ziemer, J., Ervin, J., Lang, J., “Exploring Mission
Concepts with the JPL Innovation Foundry
X A-Team,” AIAA Space 2013 Proceedings,
XMI: Extensible Markup Language (XML) September 10–12, 2013, San Diego, CA
Metadata Interchange (XMI) http://www.omg.
org/spec/XMI/
287
