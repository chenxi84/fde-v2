# 5 Schedule Development

It is a best practice for the schedule to be developed in accordance with the Schedule Management
Plan. Per Section 4.3, the Schedule Management Planning sub-function produces the Schedule
Management Plan, which provides instructions for Schedule Development - to guide the development
of the IMS and associated schedule products. Specifically, the Schedule Development Plan, the first of
four sub-plans in the SMP, includes the definition of the tools and techniques appropriate to the
type/level of scheduling the P/p necessitates. The objective of the Schedule Development process is to
define, develop and deploy a scheduling capability, including the capability to display the P/p’s time-
phased activities in an IMS and to export specific outputs as required for the other Schedule
Management sub-functions as described in Chapters 6, 7, and 8. When complete, the P/p will have a
Schedule Database contained within a scheduling tool that has the capability to generate Schedule
Outputs, including an IMS with all the required Schedule Performance Measures and associated Schedule
Performance Reports, a Summary Schedule for management reporting, and an Analysis Schedule to be
27 NASA has standard procedures in place to support the early development and documentation of operational concepts during
system development. This includes Data Requirements Document (DRDs), which describe the format and content of the
information to be provided, as well as the Data Requirements List (DRL), which set forth the data requirements in each DRD.
https://www.nasa.gov/sites/default/files/files/NNK14MA74C-Attachment-J-02-Data-Requirement-Deliverables(1).pdf
28 The Integrated Program Management Report (IPMR) Data Requirements Document (DRD) Implementation Guide discusses
different options for tailoring the Data Item Description (DID), which describes overarching requirements. The IPMR is a
consolidation of the Contract Performance Report (CPR) and the IMS and is required on all new contracts when an EVMS is a
requirement. The IMS is Format 6 of the IPMR. See the NASA IPMR DRD Implementation Guide for preparation of the IPMR
DRD, https://evm.nasa.gov/reports.html. Appendix D of the NASA Earned Value Management (EVM) Implementation
Handbook provides guidance for the CPR DRD, https://evm.nasa.gov/handbooks.html. CPR Format 5 for IMS analysis can be
found at https://evm.nasa.gov/reports.html.
29 SCoPe website, https://community.max.gov/x/9rjRYg
60

used for the SRA/ICSRA. The Schedule Development sub-function will culminate with the creation of the
IMS, which supports the requirement to baseline the IMS.
5.1 Best Practices
Figure 5-1 details the best practices for Schedule Management Development.
SM.D.1 Schedule • The schedule is developed in accordance with the Schedule Management
Development Follows the SMP Plan.
SM.D.2 Schedule BoE • The Schedule Basis of Estimate (BoE) is created and maintained throughout
Provides Rationale for all the P/p’s life cycle that documents basis rationale for all elements of the
Elements of the Schedule planned schedule, assessment and analysis findings, reporting artifacts, and
primary source data, documents and other pertinent information.
SM.D.3 Schedule is Developed • The schedule is developed using tools appropriate to the type and level of
Using Appropriate Tools schedule management that the P/p requires.
SM.D.4 Schedule Activities are • The schedule is coded such that it facilitates P/p management support
Coded to Facilitate P/p processes and other programmatic functions.
Management Support
Processes/Functions
SM.D.5 Schedule is Developed • The schedule is developed using Critical Path Method Scheduling.
Using Appropriate Scheduling
Methods
SM.D.6 Schedule is Tiered • Schedule activities are collected as organized in the WBS and tiered
According to WBS according to the lower-level, related WBS items.
SM.D.7 Schedule Naming • A schedule activity naming convention is established that allows for clear,
Convention is Established concise, and differentiable activities.
SM.D.8 Schedule Activities • Schedule activities capture all approved work scope, such that all work can
Capture All Work Scope Down be allocated to complete the WBS elements in an integrated manner.
to the Work Package Level
SM.D.9 Schedule is Developed • Schedule is developed to the lowest level of detail appropriate, typically the
to Lowest Appropriate Level of work package level, as early in the P/p life cycle as possible.
Detail
SM.D.10 Schedule Activities • Schedule activities demonstrate horizontal traceability, such that they are
Demonstrate Horizontal logically sequenced using proper relationship types that account for the
Traceability interdependence of all activities and milestones.
SM.D.12 Schedule Activities • Schedule activities only use lead and lag relationships when the values
Use Minimal Lead and Lag represent real situations of needed acceleration or delay time between
Relationships activities.
SM.D.13 Schedule Activities • Schedule logic limits the use of constraints other than “As Soon As
Limit the Use of Constraints Possible” to situations that represent actual work flow.
61

SM.D.14 Schedule Activities • All activity durations are scheduled according to the same time units.
are Scheduled According to
the Same Time Units
SM.D.15 Schedule Activities • Activities are scheduled according to representative calendars that
are Represented According to appropriately distinguish between working and non-working days.
Appropriate Calendars
SM.D.16 Schedule Activity • Schedule activity durations, including associated duration uncertainties, are
Durations are Estimated Using derived based on sources and/or processes that are appropriate and
Appropriate Sources / provide the best justification for their estimation.
Processes
SM.D.17 Adequate Schedule • Adequate margin is established and allocated as part of the schedule
Margin is Identified as Part of baseline and is clearly identifiable.
the Schedule Baseline
SM.D.18 Cost and/or • The schedule includes costs and/or resources assigned to all applicable
Resources are Assigned to activities at the most appropriate WBS level.
Schedule Activities
SM.D.19 Schedule is Time • The schedule is time-phased to align with the availability of funding to
Phased provide the earliest possible finish date.
SM.D.20 Discrete Risks are • Discrete risks are quantified and mapped to appropriate activities within
Mapped to the Schedule schedule.
SM.D.21 All Schedule • The integrated master schedule (IMS) is the foundation for all schedule
Products Tie to the IMS information.
SM.D.22 Schedule • The schedule reflects vertical traceability in that any and all supporting
Demonstrates Vertical schedules contain consistent information and can be traced to the IMS.
Traceability to the IMS at all
Levels
Figure 5-1. Schedule Development Best Practices.
5.2 Prerequisites
The Schedule Development can be initiated when:
• P/p Plans, including domain-related plans
• SMP, including schedule guidance and ground rules & assumptions (GR&As)
• Other P/p GR&A documents
• The SMP sub-plan, Schedule Development Plan, which specifies the requirements,
implementation approach, and timeline for developing the IMS, is available
• The Milestone Registry is available
• The table of Activity Attributes is available
• A scheduling tool has been selected to facilitate the maintenance, documentation and control of
the IMS
62

The Schedule BoE is typically documented in conjunction with the development of the IMS, with
preliminary and baseline versions established when required and subsequent updates throughout the
P/p life cycle, as necessary. The following sections guide the P/S through the Schedule Development
process.
5.3 Understand the P/p Scope
An understanding of the complete P/p work content must exist in order for a valid schedule to be
developed. Thus, the first steps in developing a new P/p IMS include understanding the P/p work scope,
including the Work Breakdown Structure (WBS), the Organizational Breakdown Structure (OBS), the P/p
funding dynamics and Cost Breakdown Structure (CBS), and reviewing pertinent P/p agreements and
authorization documents. As more information becomes available as part of the P/p management
processes, more detailed information can be utilized to aid in the development of the planned schedule.
5.3.1 Work Breakdown Structure (WBS)
The WBS is the “what” of P/p scope. It is a product-oriented, hierarchical division of the hardware,
software, services, facilities, and other work activities that make up the total P/p scope of work. It
organizes, displays, and defines the products to be developed and/or produced and relates the elements
of the work to be accomplished to each other and the end products. The WBS also decomposes the
scope of work into manageable segments to facilitate planning and control of cost, schedule, and
technical content. The WBS is typically accompanied by a WBS Dictionary, which is a narrative definition
of each element appearing on the WBS. The WBS Dictionary describes the work content of each WBS
element in product-oriented terms and relates each element to the respective, progressively higher
levels of the structure.
A clear understanding of the work content is necessary before a valid schedule can be developed. The
P/p work scope may be captured in the P/p Plan or in a collection of other P/p documents (e.g.,
Acquisition Plan, Verification Plan, Request for Proposal, Statement of Work (SOW)/contracts, other
external agreements, including international partnership agreement, including MOUs, MOAs, etc.). P/p
scope may include information gleaned from mission concepts, trade studies, system requirements, test
and verification requirements, safety requirements, hardware and software specifications, system
design, interface design, tooling requirements/design, manufacturing standards, unique P/p ground
rules and assumptions (GR&As), known risks, etc. These inputs should be clearly articulated by the
technical team and incorporated into the WBS and WBS Dictionary. The WBS will cover all work
elements identified in the approved P/p scope of work, including both in-house and contracted efforts.
A trace between P/p Plans, agreements, and other P/p documentation helps to ensure that all work is
captured in the WBS.
Since a WBS plays such a critical role in organizing and managing a P/p, it is important to know what
attributes are involved in a sound WBS document. Listed below are several key characteristics generally
found in a complete and meaningful P/p WBS document:
• Predominantly product-oriented
• Uses correct standard level two WBS template (from NPR 7120.5 and NPR 7120.8)
• Sub-divided elements are logical, hierarchical, and easy to understand
63

• Consistent with NASA Structure Management (NSM) coding
• Includes total P/p scope of work (including contractor effort)
• Allows for work summarization at each level
• Subdivision of work (hierarchy) is aligned with system architecture (e.g., system, subsystem,
component)
• Reflects element integration and relationships
A good WBS defines the effort in measurable elements that provide the means for integrating and
assessing technical, schedule, and cost performance. Care should be taken to validate that the total P/p
scope of work is included in the WBS prior to establishing the schedule baseline. If work is not included
in the WBS/WBS Dictionary that has been approved by P/p management, then it should not be included
within the IMS. The structure and format of the schedule should closely correlate to the approved WBS
to ensure traceability and consistency in reporting. This is accomplished by including within the IMS the
correct WBS code that is associated with each schedule task for all applicable elements, such as
hardware, software, test facilities, logistical subsystems, subcontracts, international contributions, and
support systems. Task definition begins with the product-oriented WBS, extending and detailing the
WBS down to discrete and measurable tasks.
In addition to providing a framework for planning, the WBS becomes very important to the P/S by
allowing various reporting data to be selected, sorted, and summarized to meet the analysis and
forecasting needs of P/p management and to aid in Schedule (and cost) Control. For P/ps with
contractor support, the contractors are typically required to extend approved Contractor WBS (CWBS)
elements to the necessary level of detail. It should be noted that while the Agency Core Financial
System is currently limited to seven WBS levels for capturing actual P/p costs, a P/p’s technical WBS and
schedule can further extend to lower levels to ensure that work definition and progress insight is
sufficient for proper management. NPR 7120.5 and NPR 7120.8 outline WBS structures for space flight
programs and research and technology programs, respectively, and should be used as guidance on
creating WBSs for these types of P/ps. The NASA WBS Handbook provides additional examples that can
be tailored for most P/ps. 30 Starting with the approved WBS will not only help ensure that the total
scope of work is included in the schedule, but also will ensure consistency in the integration of cost and
schedule data.
Figure 5-2 provides an example of a product-oriented WBS with recommended development guidance
highlighted.
30 NASA/SP-2010-3404/REV1. NASA Work Breakdown Structure Handbook. October 2016.
https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20160014629.pdf
64

Figure 5-2. Product-oriented Work Breakdown Structure (WBS) example.
5.3.2 Integrated Master Plan (IMP)
Although not typically a NASA-developed product, in some instances, a contractor may use an
Integrated Master Plan (IMP) in conjunction with the WBS to aid in the development of its IMS. The IMP
is an event-based, top-level plan consisting of a hierarchy of P/p events, as shown in Figure 5-3. Each
key P/p event is decomposed into specific accomplishments, and each specific accomplishment is
decomposed into specific criteria.31
31 http://acqnotes.com/acqnote/careerfields/integrated-master-plan
65

Figure 5-3. Integrated Master Plan (IMP) example.
The IMP provides a PM with a systematic approach to planning, scheduling and execution.32 Both the
IMP and the IMS form the foundations for the implementation of the EVMS. The IMP should provide
sufficient definition to allow for tracking the completion of required accomplishments for each event
and to demonstrate satisfaction of the completion criteria for each accomplishment. In addition, the
IMP demonstrates the maturation of the development of the product as it progresses through a
32 The Integrated Program Management Report (IPMR) Data Requirements Document (DRD) Implementation Guide states,
“IPMR DRD shall be integrated with the Contract Work Breakdown Structure (CWBS), the Integrated Master Plan (IMP) if
applicable, Integrated Master Schedule (IMS), Risk Management Processes, Plans and Reports (where required), Probabilistic
Risk Assessment Processes and Reports (where required), the Cost Analysis Data Requirement (CADRe) and the
Monthly/Quarterly Contractor Financial Management Reports (533M/Q).” See the NASA IPMR DRD Implementation Guide for
preparation of the IPMR DRD, https://evm.nasa.gov/reports.html.
66
IM P L e v e l
E v e n t
A c c o m p lis
C rite ria
E v e n t
m
e
A c tiv ity #
A
A 0 1A
0 1 a
A 0 1 b
A 0 1 c
A 0 1 d
A 0 2A
0 2 a
A 0 2 b
A 0 3A
0 3 a
A 0 3 b
A 0 4A
0 3 c
A 0 3 d
B
B 0 1B
0 1 a
B 0 1 b
B 0 2B
0 2 a
B 0 2 b
B 0 2 c
B 0 3B
0 3 a
B 0 3 b
B 0 4B
0 4 a
B 0 4 b
B 0 4 c
B 0 5B
0 5 a
B 0 5 b
B 0 6B
0 6 a
B 0 6 b
B 0 6 c
T a s k N a m e
E v e n t A - In te g ra te d B a s e lin e R e v ie w / P D R (IB R / P D R )
M a n a g e m e n t P la n n in g R e v ie w e d
P ro g ra m O rg a n iz a tio n E s ta b lis h e d
In itia l C o n fig u ra tio n M a n a g e m e n t P la n n in g C o m p le te d
In itia l In te g ra te d M a s te r S c h e d u le R e v ie w e d
R is k M a n a g e m e n t P la n R e v ie w e d
B a s e lin e D e s ig n R e v ie w e d
R e q u ire m e n ts B a s e lin e C o m p le te d
R e v ie w o f E x is tin g B a s e lin e E n g in e e rin g D ra w in g s C o m p
IB R C o n d u c te d
IB R M e e tin g C o n d u c te d
IB R M in u te s a n d A c tio n Ite m s G e n e ra te d
P D R C o n d u c te d
P D R M e e tin g C o n d u c te d
P D R M in u te s a n d A c tio n Ite m s G e n e ra te d
E v e n t B - C ritic a l D e s ig n R e v ie w (C D R )
D e s ig n D e fin itio n C o m p le te d
D e s ig n D e lta s to B a s e lin e Id e n tifie d
D ra w in g s C o m p le te d (B a s e lin e & D e lta )
S y s te m P e rfo rm a n c e A s s e s s m e n t
U p d a te d D ra w in g s a n d S p e c ific a tio n s R e v ie w e d
A n a ly s is R e s u lts R e v ie w e d
T e s t R e s u lts R e v ie w e d
M is s io n P e rfo rm a n c e P re d ic tio n s R e v ie w e d
A n a ly s is R e s u lts R e v ie w e d
T e s t R e s u lts R e v ie w e d
P a y lo a d In te g ra tio n P la n R e v ie w e d
P a y lo a d D e s ig n R e v ie w e d a t th e S y s te m L e v e l
P a y lo a d T e s tin g (C o m p o n e n t, F u n c tio n a l, S ta tic ) R e v ie w
S a fe ty a n d F a ilu re A n a ly s is R e v ie w e d
In itia l T e s t P la n R e v ie w e d
In itia l T e s t S c h e d u le R e v ie w e d
In itia l T e s t R e q u ire m e n ts R e v ie w e d
C ritic a l D e s ig n R e v ie w (C D R ) C o n d u c te d
IB R / P D R M in u te s a n d A c tio n Ite m C lo s u re P la n F in a liz e d
C D R M e e tin g C o n d u c te d
C D R M in u te s a n d A c tio n s G e n e a ra te d
le te
e d
d
W B S
--1
.2 .1
1 .2 .2
1 .2 .1
1 .2 .1
-1
.3 .1
1 .1 .1
.2 .1
1 .2 .1
.3 .2
1 .3 .2
--1
.1 .1
1 .3 .1
.3 .1
.3 .2
.3 .3
1 .3 .5
.2 .1
1 .2 .2
.2 .2
R e fe re
, 1 .3 .1
n c e

disciplined systems engineering process. The IMP events are not tied to calendar dates; each event is
completed when its supporting accomplishments are completed and when this is evidenced by the
satisfaction of the criteria supporting each of those accomplishments. The IMP is generally contractually
binding and becomes the baseline execution plan for the P/p. Although fairly detailed, the IMP is a
relatively top-level document in comparison with the IMS. The IMS relates to the IMP in that it shows all
the detailed tasks required to accomplish the work effort contained in the IMP in a time-based network
of activities. Thus, the IMP outline code should be traceable to both the WBS and the IMS with all tasks
containing an appropriate IMP assignment, if/when applicable.
The IMP and IMS are valuable tools a PM can use in preparing for a Request for Proposal (RFP) and
Source Selection because they serve as the basis of an offeror’s proposal and evaluation criteria. The
IMP and IMS should clearly demonstrate that the P/p is structured and executable within schedule and
cost constraints and with an acceptable level of risk. Thus, both the IMP and IMS are key ingredients in
P/p planning, proposal evaluation, source selection, and program execution.33 However, the IMP is not
a NASA-required product.
5.3.3 Organizational Breakdown Structure (OBS)
The OBS is the “who” of P/p scope. It is the hierarchical division of the organization structure that
defines who performs the work. Many P/ps require resources from more than one organization or
department. The use of a P/p OBS helps to identify the responsibilities, hierarchy, and interfaces
between these organizations. An OBS may be established regardless of whether the organization is
structured by function, Integrated Product Teams (IPT), or by matrix assignment. An OBS, if used,
should reflect the organizational responsibilities as they pertain to the P/p. This may or may not differ
from the functional organizational hierarchy. One example of an OBS is shown in Figure 5-4.
Figure 5-4. Organizational Breakdown Structure (OBS) example.
33 Department of Defense. Integrated Master Plan and Integrated Master Schedule Preparation and User Guide. Version 0.9.
October 21, 2005. http://acqnotes.com/acqnote/careerfields/integrated-master-plan.
67

The OBS also identifies the resources available to assign to work activities and to resource load the
schedule. When combined with the WBS, the OBS is used to develop a responsibilities assignment
matrix (RAM), which clearly identifies which organization is responsible for each task in the schedule as
shown in Figure 5-5. RAMs are typically used to identify control accounts, which are described in the
following section, in support of the EVMS.
Figure 5-5. Responsibility Assignment Matrix (RAM) example.
5.3.4 Cost Breakdown Structure (CBS)
The Cost Breakdown Structure (CBS), also sometimes referred to as the Resource Breakdown Structure
(RBS), is the “how much” of P/p scope. It is the hierarchical structure that classifies resources into
control accounts. At the highest level, these are labor, travel, materials, equipment, and other direct
and indirect costs. As shown in Figure 5-5, the intersection of the OBS and the WBS defines the control
account. A control account is a natural management point for planning and control since it represents
the work assigned to one responsible organizational element (or integrated product team) for a single
WBS element. A control account is also the point at which budgets (resource plans) and actual costs are
accumulated and compared to earned value for management control purposes. The person accountable
for planning and managing the resources authorized to accomplish the work effort in the control
account is the Control Account Manager (CAM). The CAM is usually responsible for the creation, status,
and maintenance of the schedule activities within the control account. Establishing the control accounts
helps to ensure that no duplication of responsibility occurs, and it lies the foundation for fully
integrating all aspects of P/p planning, including scope, schedule, budget, work authorization, and cost
accumulation processes in support of the EVMS.
68

Typically for NASA P/ps, the WBS is the primary source for development of the CBS, with each control
account being consistent with a work package or detailed task.34 If composed with cost information, a
WBS may serve directly as a CBS. Otherwise, it may be loaded with cost information attributed to its
respective elements to create the CBS. A resource- or cost-loaded schedule can be used as a tool that
yields insight and assistance to the P/p management team in their management of weekly and monthly
“resource” allocations. It assists the P/p with the on-going evolution of P/p budget estimates that
satisfy various Agency, program, and P/p budget development needs. For example, cost loading ensures
the P/p has a complete and consistent performance baseline (or formal PMB, if applicable) that includes
integrated cost and schedule for all elements of the Work Breakdown Structure (WBS). Because it is not
uncommon for the cost-estimating tool and the IMS to differ in WBS at lower-levels, it may be necessary
to roll-up, or otherwise adjust, the cost estimate in order to align the WBS levels in both tools. When
cost and schedule are developed jointly, cost loading verifies alignment at the lowest level of the cost
WBS (schedule WBS is likely at a much lower level). The integration of programmatic (cost, schedule,
risk) and technical elements provides a better understanding of how programmatics are interrelated.
For example, the dependencies between cost increases associated with schedule slips (due to potential
risks, poor performance, uncertainty, or any other constraint) or possibly even cost decreases with
schedule duration reductions (opportunity, risk mitigation, additional funding, etc.) represent how an
overall plan may be affected by changes in any element. Additional information on Resource and Cost
Loading can be found in Section 5.5.12. Additional information the CBS can be found in the NASA Cost
Estimating Handbook, Appendix B.
In some cases, the schedule may or may not directly include elements of the CBS (i.e., resource or cost
loading the schedule). Depending on the specific cost models or estimating approaches the cost analyst
has chosen, the P/p WBS may not have sufficient granularity, or misalignment may exist between the
WBS and the estimating methods. Any adjustments that are made to the P/p WBS must be coordinated
with the P/p to ensure that the changes will not cause issues with understanding or communicating the
estimate.35
The CBS should be traceable to the P/p budget. Budget planning information (i.e., all estimated P/p
costs and obligations including FTEs, WYEs, ODCs, procurements, travel, facilities, and other costs for
each fiscal year during all phases of a P/p) is used during Schedule Management Planning and Schedule
Development, leading to an approved baseline IMS. Having a clear understanding of the budget, and
specifically, the funding that will be available is critical to establishing a credible Schedule BoE, as the
IMS should be traceable at some level to the P/p CBS. This information aids in determining IMS task
durations, interdependencies, constraints, and calendars.
It is imperative that the baseline IMS correlates to and is in agreement with all segments of the
integrated cost and schedule baseline, in order to establish a good baseline to which performance can
be measured. For instance, the PMB is the time-phased cost plan for accomplishing all authorized work
scope in a P/p's life cycle, which includes both NASA internal costs and supplier costs. The P/p's
34 NASA Cost Estimating Handbook, V4.0. February 2015. Appendix B. Page B-2.
https://www.nasa.gov/sites/default/files/files/01_CEH_Main_Body_02_27_15.pdf
35 NASA Cost Estimating Handbook, V4.0. February 2015. Appendix B. Page B-2.
https://www.nasa.gov/sites/default/files/files/01_CEH_Main_Body_02_27_15.pdf
69

performance against the PMB is measured using EVM, if required, or other performance measurement
techniques if EVM is not required. Figure 5-6 illustrates the how cost and schedule are linked together
to inform the PMB.
Figure 5-6. Cost and schedule estimates must be integrated to establish a credible PMB.
Having a clear understanding of the budget, and specifically, the funding that will be available to a P/p
and when is critical in establishing a credible IMS. Funding levels and phasing may restrict the amount
of work that can be done in a specific time period forcing the P/p to replan or, if severely constrained,
may lead the P/p to descope (i.e., minimize or delete some requirements). Thus, it is important to
understand whether the P/p scope can be accomplished per the available funding given the costs
associated with the planned work. Incorporating costs into a P/p IMS provides a time-phased spending
estimate (i.e., cost-loaded schedule) that can be compared to funding availability over time. If there are
misalignments, the P/p has the data needed to re-phase the planned work or to descope the
requirements to match available budget.
Caution. During the planning process, it is important to ensure the P/p commitments never exceed the
authorized P/p funding for a specific fiscal year and do not exceed the planned annual budget for
complete LCC. Remember that P/p funding and the P/p budget are different entities, but they are
related. NASA funding is incremental, almost always by FY, and refers to the dollars authorized for P/p
expenditure during that FY. On the other hand, a P/p budget plan refers to the value assigned to the
time-phased resources necessary to accomplish the scheduled effort. There should always be
integration between funding, planned budget, and the associated work content to be scheduled. In
Figure 5-7, an authorized budget plan is shown as a function of FY.
70

Figure 5-7. Relationship between P/p phasing and P/p budget.
The P/S must work with the P/p to schedule the work such that the P/p estimated cost with
Management Reserve (MR) does not exceed the authorized budget plan for any FY. It is important to
understand the difference between MR and UFE.
• Management Reserve (MR). MR is an amount of the total P/p “budget” withheld for
management control rather than designated for accomplishment of a specific task or set of
tasks. MR is typically set aside for unforeseen and unplanned events. MR is not included in the
performance baseline (or official PMB, if applicable.) In other words, no scope is assigned to
MR. MR is typically held at the total P/p or contract level. MR should not be used to cover past
performance variances. Expected uses of MR include:
o Budgeting work that is within the P/p or contract scope (not for external changes);
o Replanning future work based on improved knowledge, such as work method/sequence,
make/buy decision changes, changes to planning assumptions, etc.
o Budgeting for the realization of known/unknown risks, or as buffer to offset risk
• Unallocated Future Expense (UFE). Although not included in the performance baseline (or
official PMB, if applicable), UFEs are the costs expected to be incurred but cannot yet be
allocated to a specific WBS sub-element of the P/p’s plan because the estimate includes risks
and specific needs that are not yet known. In other words, UFE is the “funding” that is provided
to accommodate the realization of risk and uncertainty associated with a cost or schedule
estimate. UFE may also be used for overruns and for changes within the scope of the P/p.
Management control of some or all of the UFE may be retained above the level of the P/p (i.e.,
Agency, Mission Directorate, or Program). These funds may ultimately be distributed to
mitigate the risk, to make the product work, or to accommodate cost or schedule growth, but
71
M$
,tsoC
0
6
6
2 0 1 5
C o s t
P h a s in
2 0 1 6
o s t E stim
g
a te
v e r s u s A u t h
2 0 1 7
F is c a l Y e
P / p H e ld U F E
o r
la n
a r
iz e d B
n e d A
0 1 8
H Q H e
u d g
n n u a
ld U F E
e t
l B
2 0 1
u
d g e t L e v e
2 0
l
2 0

because not all risks or uncertainties will be realized, initial allocation of funds to particular WBS
elements would be premature. During a P/p’s KDPs, the Decision Authority typically determines
whether UFE is necessary, and documents the decision in a Decision Memorandum. For P/p’s
with a JCL requirement, UFE is typically established by exercising probabilistic techniques, and is
the portion of estimated cost required to meet a specified JCL. The JCL is further described in
Section 6.3.2.4, as well as in the NASA Cost Estimating Handbook, Appendix J.
5.3.5 Integrated Master Schedule (IMS)
The Integrated Master Schedule (IMS) is the “when” of P/p scope. It supports all internal NASA P/p and
all external contractor activities, when applicable. The purpose of an IMS is to provide a time-phased
plan for performing the P/p’s approved total scope of work and achieving the P/p’s goals and objectives
within a determined timeframe. Whether developed for a Program or project, the IMS contains tasks,
milestones, and interdependencies logically sequenced in a manner that accurately models the
implementation plan for all approved scope from P/p start through completion based on all P/p work as
defined/broken down by the established WBS. The IMS also provides management a vehicle which
enables integration of the approved P/p work scope reflected in the work breakdown structure (WBS),
cost estimate, and programmatic risks to ensure alignment with the P/p’s integrated performance
baseline (or PMB). This includes both government and contractor work. The detail is sufficient to
identify the longest path of activities through the entire P/p. Prior to establishing the baseline, the
schedule is referred to as the preliminary schedule or preliminary IMS; once baselined, it is the schedule
baseline or baseline IMS. Figure 5-8 shows an example of a schedule that integrates the “who”, “what”,
and “how much” of the P/p scope.
Figure 5-8. Integrated Master Schedule (IMS) example that ties together all aspects of the P/p scope.
The remainder of this Chapter discusses: (1) the Schedule BoE, which documents the ground rules and
assumptions (GR&A), constraints, and any other rationale that dictates how the IMS is developed, and
(2) the development of the IMS. The IMS is further discussed in Section 5.6.1.
5.4 Develop the Basis of Estimate
It is a best practice for a Schedule Basis of Estimate (BoE) to be created and maintained throughout
the P/p’s life cycle that documents basis rationale for all elements of the planned schedule,
72

assessment and analysis findings, reporting artifacts, and primary source data, documents and other
pertinent information. As defined by NPR 7120.5, “a Basis of Estimate (BoE) is the documentation of
the ground rules, assumptions, and drivers used in developing the cost and schedule estimate, including
applicable model inputs, rationale or justification for analogies, and details supporting cost and schedule
estimates.”36 The Schedule BoE dossier acts as a comprehensive, structured collection of technical and
programmatic information necessary to fully develop, understand, assess, analyze, and theoretically
reproduce the IMS, while also playing a supplementary role in schedule maintenance and control. A BoE
ideally serves in the following critical capacities:
• Enables the development of the IMS by capturing basis rationale alongside primary data sources
and reinforcing methodological consistency.
• Provides a medium for assessing schedule reliability, the ultimate measure of schedule quality.
• Guides schedule evolution through expert dialogue and discovery of evidence for specific
schedule improvements
• Captures the end-to-end narrative of the P/p through the lens of schedule for the benefit of in-
line practitioners and agency community of practice
• Enables dialogue and streamlined information exchange between the P/p and Independent
Assessment teams
Populating the Schedule Database necessitates the development and maintenance of a robust BoE in
order to ultimately produce an IMS that can be considered reliable. The BoE should include places for
basis rationale associated with all data that feeds into the Schedule Database. The BoE should complete
the trace from all basis rationale to primary sources of data used to develop the schedule by including all
referenced material in some form. This handbook therefore provides no specific BoE template or
format, though it is necessary that the P/p’s BoE always house both the current and past versions of the
IMS alongside counterpart incarnations that can be easily annotated and tracked by P/Ss, according to
the Schedule Documentation processes described in Section 8.3.3.
Note: Hereafter in this document, the schedule BoE dossier will be referred to simply as the “BoE”. It is
noted where the Schedule BoE should be differentiated from other types of “basis of estimate”
documents (like those pertaining to cost).
5.4.1 BoE Maturity by P/p Phase
It is a requirement for P/ps that are governed by NPR 7120.5, which states, “all programs and projects
develop cost estimates and planned schedules for the work to be performed in the current and
following life cycle phases (see Appendix I tables). As part of developing these estimates, the program
36 NPR 7120.5E. NASA Space Flight Program and Project Management Requirements. Effective Date: August 14, 2012.
Expiration Date: August 14, 2020. Appendix A.
https://nodis3.gsfc.nasa.gov/npg_img/N_PR_7120_005E_/N_PR_7120_005E_.pdf
73

or project shall document the BoE in retrievable program or project records.”37 A table of the required
BoE maturity at given LCRs is provided in Figure 5-9.38
Figure 5-9. Schedule BoE maturity requirements by P/p phase according to NPR 7120.5.
Although not explicitly identified in NPR 7120.8 as a required product for R&T P/ps, it is expected that a
BoE would exist at a maturity corresponding to the maturity of the IMS. It is also important to note that,
“R&T projects that directly tie to the space flight mission’s success and schedule are normally managed
under NPR 7120.5.” Figure 2-3 and Figure 2-4 provide an overview of the expected maturity of the BoE
for P/ps that adhere to NPR 7120.8.
BoE endures across the life cycle; its structure and maturity is phase-dependent. For Uncoupled and
Loosely-Coupled Programs, a preliminary BoEs is required at SRR, with a baseline at SDR, and updates at
subsequent LCRs. For Tightly-Coupled Programs, preliminary BoEs are required at SRR and SDR, with a
baseline at PDR, and updates at subsequent LCRs. For projects, preliminary BoEs are required at MCR,
SRR, and SRR/MDR, with a baseline at PDR, and updates required in conjunction with the maturity of the
schedule at each life cycle review. It is important to note that the BoE will evolve as the P/p matures.
For example, a project’s BoE for Phases E and F is not required until SIR.
Early in Formulation, the P/p may need to rely on historical data from past P/ps to estimate the overall
schedule duration. Pre-Phase A and Phase A typically use analogies provided by tools or databases that
37 NPR 7120.5E. NASA Space Flight Program and Project Management Requirements. Effective Date: August 14, 2012.
Expiration Date: August 14, 2020. Page 37.
38 While NPR 7120.8A does not specifically require a Basis of Estimate (BoE) product, projects that adhere to NPR 7120.8 may
benefit from the documentation of BoEs to support the required programmatic products.
74
ytirutaM
etamitsE
fo
sisaB
dna
delpuocnU
delpuoC
ylthgiT
delpuoC-ylesooL
stcejorP
S R
P re lim
S R R
P re -P h a s e A
K D P A
M C R
In itia l (fo r
ra n g e )
Rin
a
K
F o rm u la tio n
ry
D P 0
S D R
P h a s e A
K D P B
S R R S D R / M D
U p d a te U p d a te
(fo r (fo r
ra n g e ) ra n g e )
B
S D R
a s e lin e
K D P 1
P h a s e B
K D P C
U p d a te fo r
c o s t a n d
s c h e d u le
e s tim a te
C D
K D
p d a te
P h a
K D
C D R
Im p le m e n ta tio
K D P I
P IR
P II K D P III
S IR O R R M R R / F R R
U p d a te U p d a te U p d a te
s e C P h a s e D
P D K D P E
S IR O R R M R R / F R R
U p d a te U p d a te U p d a te
P h a s e E
K D P F
D R
P IR n
D R
h a s e F
D R R

store historical information, such as SMART, the Schedule Repository, CADRe, and NICM.39 A summary
of these tools and databases can be found in Section 5.5.9.3.2.
While it is likely that some historic data will be available for most P/ps, in the cases of new technologies,
there may be instances where analogous data does not specifically exist (e.g., new technology
developments, etc.). In these cases, the P/S and/or Schedule Analyst should increase the amount of
uncertainty, and perhaps the point estimate itself, to account for the lack of relevance to the analogy.
Any assumptions made concerning the derivation of uncertainty and durations should be documented in
the BoE and the IMS, as well as ensuring the IMS has the appropriate amount of float and/or margin.
In subsequent phases, documentation will have been generated specific to the P/p with more detailed
information, and the schedule will be more detailed by means of the rolling wave or similar approach.
By PDR, when the schedule is more detailed, defining all work required to accomplish the complete P/p
effort, the basis rationale for the selected durations, the duration uncertainties, and any other specific
attributes for the activities should be captured in the BoE. Attributes of the activities to include in the
BoE may include, but are not limited to:
• Activity owners
• Workflow logic
• WBS, OBS, and CBS identifiers (WBS Dictionary should provide appropriate description of the
work effort that is represented by schedule activities)
• Work package identifiers
• Shifts required
• Duration and duration uncertainty with associated rationale
• Other assumptions and/or constraints
Thoroughly documenting the BoE also aids the P/S in carrying out the Schedule Assessment procedures,
such as the Requirements Check, described in Section 6.2.2.1.1, and the Basis Check, described in
Section 6.2.2.2.2.
5.4.2 Source Information to Inform the BoE
All P/p documentation available should be reviewed and used to support Schedule Development,
including the documentation of the BoE, as these documents may contain many of the ground rules,
assumptions, and drivers for the P/p. The following is a list of typical P/p products that P/S should have
access to and be very familiar with when starting the Schedule Development sub-function:
39 The Cost Analysis Data Requirement (CADRe), the Schedule Management and Relationship Tool (SMART), the Project Cost
Estimating Capability (PCEC), and the NASA Instrument Cost Model (NICM) can be found on the One NASA Cost Engineering
Database (ONCE), www.oncedata.msfc.nasa.gov. REsource Data STorage And Retrieval System (REDSTAR) access can be
requested through the NASA Access Management System (NAMS), https://www.hq.nasa.gov/office/itcd/nams.html.
75

• P/p Plans (see Appendix I in NPR 7120.5 for the types of P/p Plans required and their associated
maturity by phase)
• Agreements and Authorization Documents (e.g. Formulation Agreement Document, Decision
Memorandums, etc.)
• Scope Definition
o Work Breakdown Structure (WBS) and WBS Dictionary
o Integrated Master Plan (IMP), if available
o Organizational Breakdown Structure (OBS)
o Cost Breakdown Structure (CBS)
• Cost Estimate/BoEs
o Program Planning Budget Execution (PPBE) data
o Request for Proposal (RFP) or Contract
▪ Task Agreements (TA)
▪ Data Requirements Document (DRD)
▪ Bill of Materials (BOM)
o Core Financial Business Warehouse Reports
• P/p Risk Information (Risk Management Plan) and Database
o Risk Statements and Context
o Risk Matrix, including Likelihood (probability) and Consequence (duration distributions)
o Risk Impact descriptions (cost, schedule, technical)
o Risk Mitigation descriptions (incl. cost and schedule requirements, technical aspects)
These sources provide critical insights regarding overall P/p scope and duration needed for developing a
schedule with a valid basis, such as: correct task sequencing, responsibilities, task duration, and
resource information.
It is important to realize that P/p personnel may not have the same interpretation or understanding of
the approved SOW. Resolving these differences is necessary for the development of an accurate and
useable schedule for P/p management. The P/S can play a significant role in helping to resolve these
differences by asking the right questions (e.g., In what WBS element does specific effort belong? What
type of deliverable is required? What type of testing is required?), and by bringing to light the areas of
conflict so that responsible managers can come to an agreement on the work scope. For example, the
P/S should always help the P/p team understand the necessary inputs (e.g., responsibility, in-house or
contracted effort, quantities, and facility requirements) to task and schedule definition, as well as the
inherent interfaces involved. In addition, and equally important to capturing the complete scope of the
P/p in Schedule Development is documenting any exclusions and risks to the P/p, as these are P/p
attributes that may affect the Schedule Management approach. Per NPR 7120.8, a Research and
76

Technology (R&T) P/p tends to define a cost/schedule structure rather than an LCC and associated end
date. Thus, it is important to understand the complete scope that will take the R&T P/p to its end date.
If relevant data or documentation has not been developed, the P/S should lead or otherwise galvanize
development of these documents. More information on how the P/S might interface with other PP&C
functions are included described in the PP&C Handbook.40 By initially gathering and understanding as
much of this data as possible, the effort will lead to a more accurate and meaningful schedule for use in
guiding P/p management.
5.4.3 Documenting the BoE in Conjunction with Developing the IMS
Documenting the basis rationale for Activity Attributes initializes the BoE, along with capturing primary
data sources. This activity should be done in conjunction with developing the IMS as defined in Section
5.5, as well as any capturing any related assumptions or rationale from the assessment of the IMS as
described in Chapter 6.
As the P/p continues through its life cycle and changes are made to the IMS, the rationale for changes
and supporting data should be captured within the BoE and tracked through the P/p’s change control
process, as described in Chapter 7.
5.5 Develop the Schedule
Schedule Development is a function initiated early in the Formulation of a P/p and is accomplished by
following the requirements and the Schedule Development Plan in the SMP. Schedule Development
activities should be performed according to the P/p life cycles as follows:
• Pre-Phase A (Pre-ATP): Initialize documentation within the preliminary BoE. Implement the
scheduling methodology and tools. Establish data fields that correspond with the planned
Activity Attributes. Begin developing preliminary IMS.
• Phase A-SRR (ATP): Initiate loading the Schedule Database to capture the entire scope of work
for the P/p that support the milestones identified in the planned Milestone Registry. Define
relationships and constraints of the activities. Assign resources. Continue developing and
testing the preliminary IMS and its associated Schedule Database. Continue documenting the
Schedule BoE.
• Phase A – SDR/MDR: Update the preliminary IMS. Continue Schedule Assessment and
commensurate BoE development.
• Phase B – PDR (Program Approval): Baseline the IMS and its BoE. Develop an Analysis Schedule,
if necessary.
• Phase C/D – CDR/SIR/ORR through Launch (PARs through Closeout): Continue developing the
IMS per the rolling wave approach, if applicable. Continue developing the Analysis Schedule, if
necessary.
40 https://nen.nasa.gov/documents/879593/1386755/PP%2BC+Handbook+1-5-17.docx/097acedf-1df7-4676-b9c1-
4c0c1e83dc2e?version=1.0&download=true
77

Figure 5-10 illustrates how the implementation of the SMP results in a time-phased set of activities that
aligns the development and deployment of the IMS and associated products with the continuous
Schedule Management processes according to the P/p life cycle. The continuous Schedule
Management processes that are executed throughout the P/p life cycle according to three of the sub-
plans in the SMP include:
• Schedule Assessment and Analysis, Chapter 6
• Schedule Maintenance and Control, Chapter 7
• Schedule Documentation and Communication, Chapter 8
Figure 5-10. Schedule Development and its relationship to the other Schedule Management processes.
The primary output of Schedule Development is the IMS, although other Schedule Outputs, such as a
Summary Schedule or an Analysis Schedule may be produced, in addition to Schedule Performance
Measures. Schedule Outputs and Schedule Performance Measures are further defined in Section 5.5.13.
5.5.1 Ensure Scheduling Tool Capabilities
It is a best practice for the schedule to be developed using tools appropriate to the type and level of
schedule management that the P/p requires. Choosing the right schedule management tools is critical
to success, not only for the P/p team, but also for any contractors involved. It should be clearly
78

understood during up-front P/p planning and process development that there are numerous
management tool sets available that do not allow for easy and/or accurate transfer and integration of
schedule and performance data. It is crucial for achieving successful P/p management that tools, which
provide efficient and accurate transfer and integration of data, be chosen, and where possible,
mandated for all P/p participants. At a minimum, scheduling tools should satisfy the following
capabilities:
Functional
• Provide for entering and editing of baseline plan, current/forecast plan, and accomplished
(actual) schedule data
• Specify relational dependencies between tasks and milestones (including lag and lead values as
needed, but kept to a minimum)
• Define P/p calendars that reflect the business schedule (e.g., workdays, non-workdays, holidays,
and work-hours)
• Display and print P/p schedules in Gantt and network diagram form
• Calculate total slack (float) and free slack for all P/p tasks and milestones
• Provide user-defined code fields for filtering, grouping, summarizing, and organizing data, and
mirroring BoE-related information where appropriate
• Create, view, and print basic reports such as task, cost, and resource listings
• Provide capability for cost loading, and resource loading and leveling
Technical
• Supports email capability of schedule data in native file formats
• Uses Open Database Connectivity (ODBC) or Dynamic Data Exchange (DDE) standards to
read/write to other databases
• Provides capability of saving data files such as MPX, DBF, XML, HTML, and X-12
• Provides online “help” capability
• Provides capability for creating PDF files or graphic files such as: jpeg, bmp, gif, or tif
Interface
• Supports data interface to chosen in-house EVM applications (e.g., Internally developed EVM
spreadsheets or commercial EVM applications)
• Supports data interface to EVM data analysis applications
• Supports data interface to schedule risk analysis applications, such as range estimates and JCL
analyses
79

MS Project and Oracle Primavera P6 are common scheduling tools that are used throughout the Agency
and can handle differing levels of schedules and integration with other PP&C tools and data. Both on-
site and cloud versions (such as MS Project Server) generally meet the capabilities listed above.
Document the BoE for the Scheduling Tool
Scheduling tool selection should be documented in the Schedule Development Plan. Documentation of
the specific tool selection and the corresponding rationale is considered part of the BoE. The P/S
document that the tool selected is compliant with the P/p requirements and the requirements. The P/S
should also ensure that any additional tools used to create, house, and maintain the entire Schedule BoE
are compliant with the requirements and execution techniques pertaining to the BoE as outlined in this
chapter and Section 6.2.
5.5.2 Establish Schedule Field Codes
Information in the schedule should be consistent with key documents and other information through
activity codes.41 It is a best practice for the schedule to be coded such that it facilitates P/p
management support processes and other programmatic functions. Coding of activities can aid in
organizing, displaying and reporting schedule information in useful formats. Appropriate coding can
also facilitate consistent vertical schedule traceability, as well as help to filter and summarize schedule
data to provide reports at the summary, intermediate, and detail schedule levels, as needed. The coding
structure can be as basic or as comprehensive as necessary for the P/p’s needs.
Developing the table of Activity Attributes is available as a prerequisite to Schedule Development. The
table specifies the fields needed in the IMS to interface with other P/p management process as well as
provides additional information that the P/p needs. The fields need to be allocated during the Schedule
Development process. The minimum set of Activity Attributes that require coded fields in the schedule
are shown in Figure 5-11.
41 GAO-16-89G. GAO Schedule Assessment Guide. Page 24. December 2015. http://www.gao.gov/assets/680/674404.pdf
80

Figure 5-11. Example of a typical Activity Attributes table.
There are an infinite number of field and field codes that either exist or can be created. The tools used
along with the P/p characteristics determine the limitations on this parameter. The number of field
codes needed for a P/p will vary widely, depending on many factors such as P/p size, maturity, industry
or technology, complexity, entities involved, phase, and so on. The appropriate number of field codes to
use is the number required to effectively and efficiently manage the P/p. The same can be said for the
types of field codes to use. Field codes can be set using different code types, such as Flag, Number,
Text, and Date codes. Commonly-used field codes include:
• WBS. The WBS defines hierarchical organization of the work to be executed by the P/p team.
The WBS is an important coding structure that when incorporated into the IMS, aids in
extracting and formatting desired schedule data.
• Control Account Code (and/or CWBS). Although it may be different the control account code,
or CWBS, helps to map work scope to the control account from which the work is funded. Each
control account may be mapped to more than one work package, but each work package can
only be mapped to one control account. Coding schedule activities by control account is a
management tool to integrate scope, budget, cost, and schedule and can help facilitate earned
value performance measurements.
• Responsibility Code. The responsibility code can be used in a number of ways, such as a
reference to a responsible person, team, or group (e.g., Technical Lead, CAM, IPT, etc.). This is
not the same as the OBS, but rather a more specific identifier. The field code can be useful for
81
A c t iv it y A t t r ib u t e s
P ro g ra m / P ro je c t: D a te :
A c tiv ity ID : T h is in fo rm a tio n c o m e s fro m th e A c tiv ity : T h is is th e n a m e o f th e a c tiv ity fro m W B S N o : T h is id e n tifie s w h e re th is a c tiv ity
p ro je c t a c tiv ity lis t. th e p ro je c t a c tiv ity lis t. c a n b e fo u n d in th e W B S .
A c tiv ity D e s c rip tio n : T h is in fo rm a tio n in c lu d e s a d e ta ile d d e s c rip tio n o f th e w o rk to b e p e rfo rm e d fo r th is a c tiv ity a n d s h o u ld b e c o n s is te n t
w ith w h a t is p ro v id e d in th e p ro je c t a c tiv ity lis t. A c tiv ity R e s p o n s ib ility : T h is s e c tio n lis ts w h o R e s o u rc e s a n d S k ill S e ts R e q u ire d : T h is s e c tio n d e s c rib e s th e re s o u rc e s n e e d e d to p e rfo rm
is re s p o n s ib le fo r e x e c u tin g th e w o rk th e w o rk . F o r h u m a n re s o u rc e s th is s e c tio n s h o u ld in c lu d e n e c e s s a ry s k ill s e ts a n d s k ill le v e ls
a s s o c ia te d w ith th is a c tiv ity . re q u ire d to c o m p le te th e w o rk .
A c tiv ity P re d e c e s s o rs : T h is s e c tio n lis ts o th e r P re d e c e s s o r L in k R e la tio n s h ip : T h is d e s c rib e s P re d e c e s s o r D e p e n d e n c y : T h is s e c tio n
a c tiv itie s w h ic h m u s t o c c u r b e fo re th is if th e p re d e c e s s o r h a s a s ta rt-s ta rt, fin is h - d e s c rib e s a n y d e p e n d e n c ie s o n p re d e c e s s o r
a c tiv ity . s ta rt, o r o th e r ty p e o f s c h e d u lin g a c tiv itie s lik e le a d / la g tim e s o r o th e r
A c tiv ity S u c c e s s o rs : T h is s e c tio n lis ts o th e r S u c c e s s o r L in k R e la tio n s h ip : T h is d e s c rib e s if S u c c e s s o r D e p e n d e n c y : T h is s e c tio n
a c tiv itie s w h ic h m u s t o c c u r a fte r th is a c tiv ity . th e s u c c e s s o r h a s a s ta rt-s ta rt, fin is h -s ta rt, o r d e s c rib e s a n y d e p e n d e n c ie s o n s u c c e s s o r
o th e r ty p e o f s c h e d u lin g re la tio n s h ip . a c tiv itie s lik e le a d / la g tim e s o r o th e r
T y p e o f E ffo rt: T h is s e c tio n if th e w o rk fo r th is a c tiv ity is a le v e l o f e ffo rt, fix e d e ffo rt, fix e d d u ra tio n , a p p o rtio n e d e ffo rt o r o th e r ty p e o f
w o rk . L o c a tio n o f A c tiv ity : T h is s e c tio n d e s c rib e s w h e re th e w o rk fo r th is a c tiv ity w ill b e p e rfo rm e d .
A c tiv ity A s s u m p tio n s : T h is s e c tio n lis ts a ll a s s u m p tio n s a s s o c ia te d w ith th is a c tiv ity . T h e s e s h o u ld a ls o b e in c lu d e d in th e p ro je c t's
a s s u m p tio n lo g . A c tiv ity C o n s tra in ts : T h is s e c tio n d e s c rib e s a c tiv ity c o n s tra in ts s u c h a s firm m ile s to n e d a te s , re s o u rc e c o n s tra in ts o r a n y o th e r id e n tifie d
c o n s tra in ts w h ic h m a y im p a c t th is a c tiv ity .
A c tiv ity U n c e rta in ty D u ra tio n M in : T h is A c tiv ity U n c e rta in ty D u ra tio n M / L : T h is A c tiv ity U n c e rta in ty D u ra tio n M a x : T h is
s e c tio n lis ts th e m in im u m n u m b e r o f s e c tio n lis ts th e m o s t lik e ly n u m b e r o f s e c tio n lis ts th e m a x im u m n u m b e r o f
u n c e rta in d a y s th a t c a n im p a c t th e a c tiv ity . u n c e rta in d a y s th a t c a n im p a c t th e a c tiv ity . u n c e rta in d a y s th a t c a n im p a c t th e a c tiv ity .
R is k L ik e lih o o d : T h is s e c tio n lis ts th e R is k D e s c rip tio n : T h is s e c tio n p ro v id e s d e ta ils a b o u t th e c a u s e s a n d e ffe c ts o f th e ris k .
lik e lih o o d o f a ris k 's o c c u rre n c e . P le a s e n o te th a t th e re c a n b e m u ltip le ris k s .
A c tiv ity R is k D u ra tio n M in : T h is s e c tio n lis ts A c tiv ity R is k D u ra tio n M / L : T h is s e c tio n lis ts A c tiv ity R is k D u ra tio n M a x : T h is s e c tio n lis ts
th e m in im u m n u m b e r o f d a y s th a t th e ris k th e m o s t lik e ly n u m b e r o f d a y s th a t th e ris k th e m a x im u m n u m b e r o f d a y s th a t th e ris k
c a n im p a c t th e a c tiv ity . c a n im p a c t th e a c tiv ity . c a n im p a c t th e a c tiv ity .

sorting and grouping of data into distinct work groups. The result may then be used to collect
status, plan resources, or to communicate a group’s work plans.
• Phase Code. The phase code may be defined in different ways, but usually as a logical grouping
of work that flows along the P/p timeline, more or less sequentially. For example, one such
definition may result in phases such as Engineering, Procurement, Fabrication, and Testing. It is
often used to organize data to facilitate interface-planning efforts and produce summary-level
reports.
• Activity Type Code. The activity type code helps to distinguish between schedule activities that
have different functions within the IMS, such as milestones, regular activities, LOE activities,
summary activities, “margin activities”, or other “placeholder activities.” Activity type coding
can facilitate Schedule Assessment, Analysis, and Control by making it easier to filter through
activities of interest. It is a recommended practice that any “activity” other than a regular
activity be coded appropriately.
• EVM Codes. The EVM code helps to filter on tasks that are used as inputs to EV metrics. the
selected IMS tasks’ Unique Identifiers (UID) are associated with a coding structure, which ties
into the EVM software used. The coding structure identifies the start and end of tasks that
support a milestone within the EVMS. The coding structures can be as basic or as
comprehensive as necessary for the P/p’s needs.
• Other Commonly-Used Codes. P/p activities may also be coded for consistency with such
information as the related contractor, location, phase, contract line item number (CLIN), work
package number, CAM, and SOW paragraph as applicable.42 Other commonly-used or
customized codes may include Activity ID, Area, System, Department, Step, Priority, Resource
Names, Resource Costs, Uncertainties, Risks, etc.
P/p management may occasionally be faced with an opportunity to become creative with regard to
coding of data. For example, schedules may need to be constructed that are adaptable to special
requirements specific to a particular report or action tracking product. In some cases, a request for
isolating a particular requirement, design, fabrication, or test phase may be requested. Most scheduling
software tools are flexible in allowing field customization for filtering, sorting, and grouping to enable
displaying specific criteria. Coding may become more informal in these cases but should still be
documented. It is a recommended practice to maintain a coding dictionary, or some equivalent
documentation, to capture field code information. In larger P/ps this document should be incorporated
by reference or inclusion in other applicable P/p documentation with changes controlled appropriately.
Once particular field codes are defined for use in a P/p, it is a recommended practice that the field code
value be used consistently for all related P/p data. Consistency is the key to a successful data structure
and coding scheme. For example, if the resource abbreviation “E” for “Engineers” has been established,
this resource abbreviation should be used in all places where a resource abbreviation for “Engineers” is
required. There may be occasions where this practice may not be practical, or even possible, due to
42 GAO-16-89G. GAO Schedule Assessment Guide. Page 24. December 2015. http://www.gao.gov/assets/680/674404.pdf
82

system limitations or incompatibilities. In these scenarios, a cross reference table can be created to
relate pertinent codes. Continuing the example above, if the P/p’s payroll tool uses the abbreviation
“Eng” for “Engineers,” but the tool has a limit of only one character for the “Engineers” resource, it may
be necessary to use “E” for Engineers in the scheduling tool. The cross-reference table in Figure 5-12
would then contain the following entry:
Data Type Data Item Payroll Tool Scheduling Tool
Resources Engineers Eng E
Figure 5-12. Example of schedule coding crosswalk to resource coding.
It is important to maintain the integrity of the data structure while enabling various users with varying
needs to query the data effectively and efficiently. Coding enables various forms of filtering, such as the
grouping or sorting of data without altering the structure. Grouping refers to the gathering of data that
share some common characteristic. Sorting refers to ordering data in an arrangement that differs from
the natural order as stored in the database. Users may find it useful, for example, to order activities by
the planned start date. Sorting by planned start in ascending order would generate a list of activities in
order they are scheduled to be worked. In some situations, it may be a desirable to group together
schedule activities that use the same resource for certain reports, for example. Grouping by values in a
resource code field would enable this function. Or, it may be desirable to group schedule tasks
together that use the same Center code for a report that would show certain data summarized by
Center. This will aid P/p personnel that need to reference or read schedules without having a detailed
understanding of the scheduling tool being used.
The use of field codes can aid in the integration of P/p management (e.g., PP&C functions). If EVM is
required, it is a recommended practice that schedule data be coded with the set of NASA-identified EVM
fields, at a minimum, since the complete set of EVM milestones comprises the PMB from a schedule
perspective. The EVM-required field codes are provided on the SCoPe website.43 Figure 5-13 shows an
example of a schedule coded with an interface to the Risk Management System, two interfaces with the
Earned Value Management System (EVMS), and an identification field listing the CAM for each activity.
43 SCoPe website, https://community.max.gov/x/9rjRYg
83

Figure 5-13. Example showing a few typical Activity Attributes coded into fields in the MS Project scheduling tool.
The project shown had approximately 20 field codes defined for information and interface with other
processes. The intrinsic fields are those that are “hard-coded” in most scheduling software. Other
important attributes often used, but not shown in the example are:
• From the Organizational Breakdown Structure (OBS), a code that identifies the organization that
is responsible for execution of the activity. Example: Power and Propulsion Division, code PPD.
• For contracted activity, a code that identifies the contract and/or a code that identifies the
contractor.
• For contracted activity, a Contract Line Item Number (CLIN).
• Flags are commonly used to identify specific classes of activities to enable quick search, e.g.,
notification milestones, control milestones, target milestones, interface milestones, critical
activities, etc.
• Sometimes integration working groups are assigned to a collection of activities that are closely
related such as APW, Avionics, Power and Wiring.
84

In a similar fashion, but not shown here, the cost database for the IMS has fields that need to be
established for the cost interface including resource name, resource costs, uncertainties, and risk
functions from the Risk Management System.
Document the BoE for the Schedule Field Codes
The table of Activity Attributes and associated field codes to be used in the IMS are considered part of
the BoE. Rationale for field code types can be captured in the table of Activity Attributes (e.g., fields
necessary to implement EVM, if required) and should include ties to the schedule content that will be
assessed, analyzed, and controlled.
5.5.3 Implement Scheduling Method
It is a best practice for the schedule to be developed using Critical Path Method (CPM) scheduling.
CPM is a logic network diagram scheduling technique used to estimate the minimum P/p duration by
calculating critical path, which is the longest path through the schedule network. Most scheduling
software supports CPM scheduling. Five approaches for characterizing the P/p IMS in support of CPM
are described in Section 5.6.1.
The essential technique for employing CPM is to construct a model of the P/p that includes the
following:
• A list of all activities required to complete the P/p (typically categorized within a work
breakdown structure)
• The time (duration) that each activity will take to complete
• The dependencies between the activities
• Logical end points such as milestones or deliverable items
Although CPM scheduling offers a visual, time-phased representation of P/p activities, the P/S should be
aware that it does have limitations when used in its most basic form:
• Based on only deterministic task duration; does not consider duration uncertainty
• Less focus on non-critical tasks that can cause risk
• Does not consider resource dependencies; assumes resources are free when needed
• Misuse of float/slack (work expands to fill the time)
• Early finishes (time gains) not effectively being used by subsequent activities (typically due to
early start dates not accounting for resource availability or lack of resource-informed schedule)
Thus, it is a recommended practice for NASA P/ps to use CPM scheduling in an expanded form to include
the integration of other programmatic aspects (e.g., cost, risk, etc.), which provides a more integrated
and holistic representation of the P/p. For instance, CPM scheduling is more effective and informative
when risks and resources and/or costs are integrated into the schedule. If management focuses solely
on critical activities without taking into account critical resources, it risks ignoring or overworking a P/p’s
85

most valuable assets and potentially jeopardizing the P/p’s timely completion.44 If management does
not consider the potential discrete risk impacts to a schedule, it may not be managing to the path most
likely to delay the P/p.
Document the BoE for the Scheduling Method
Because CPM scheduling is a best practice, it is necessary to document the rationale for any portions of
the schedule that use alternate scheduling methods (e.g., agile) in the BoE. It is important to
understand how schedules or portions of the schedule that do not employ CPM scheduling may affect
assessment metrics and analysis results.
5.5.4 Determine Schedule Hierarchy
It is a best practice for the schedule activities to be collected as organized in the WBS and tiered
according to the lower-level, related WBS items. The IMS structuring is particularly important to
facilitate supporting P/p management processes and functions. For example, in most cases, the WBS is
the primary structure of the EVMS. Whether or not EVM is required, activities should be organized in a
sequential, waterfall approach. In general, a sequence of events should be broken down such that when
one activity finishes, another starts. While this approach may not always be possible, if the schedule is
developed using this approach, the effort of logically connecting the activities will be much easier. It is
important to avoid up/down flows because such an arrangement greatly complicates the checking,
verification and performance tracking, as well as the schedule assessment process. This process is
facilitated by the field codes setup in Section 5.5.2. Figure 5-14 shows an example, where activities are
loaded in a waterfall method starting with the P/p start date.
Figure 5-14. Load the activities in a waterfall fashion, earliest first.
44 GAO-16-89G. GAO Schedule Assessment Guide. Page 87. December 2015. http://www.gao.gov/assets/680/674404.pdf
86

Document the BoE for the Scheduling Hierarchy
Because the IMS requires traceability to the WBS, it is important to include in the BoE rationale for any
activity flows that are not organized according to the WBS hierarchy. Providing justification for the
hierarchy used in the schedule will aid in resource allocation and understanding the critical path, as well
as tracing accountability to the appropriate Technical Leads.
The Requirements Check, Procedure 1, should be performed at this juncture to ensure IMS traceability
to the P/p’s requirements set, which includes the WBS, as described in Section 6.2.2.1.1.
5.5.5 Determine Activity Naming Convention
It is a best practice for a schedule activity naming convention to be established that allows for clear,
concise, and differentiable activities. Each activity represents a discrete, measurable element of work
that is part of the overall P/p scope. In order to describe the work to be accomplished without
ambiguity, activity and milestone descriptions need to be unique. The P/S should work with the
Technical Lead that is responsible for the activity to develop a clear and specific description. An activity
description should also be concise yet complete – complete enough to stand on its own, but concise
enough to facilitate ease of use, such that personnel other than the P/S will be able to understand the
work scheduled. This applies to all activities, not just summary-level activities. Acronyms and
abbreviations are acceptable as long as they are standardized and used consistently throughout all P/p
documentation.
Activity nomenclature convention or methodology should be established at the beginning of the P/p and
adhered to throughout the P/p life cycle. It is a recommended practice that summary activity names be
aligned with the WBS naming structure for easier traceability. A P/p may elect to use a “noun, adjective,
modifier” or “modifier, adjective, noun” convention of for all summary activity descriptions and a “verb,
adverb, modifier” or “modifier, adverb, verb” convention for all discrete measurable activities. For
example, detailed (non-summary) activity descriptions should contain a “verb” so it is completely clear
what the accomplishment of work being scheduled is (e.g., “Fabricate CM Front Bay Access Panel
BR549”), whereas summary-level activities descriptions should not contain a verb and be more “noun”
oriented (e.g., “CM Fabrication of all Access Panels”). This type of standardized approach, if used
consistently, will make efforts such as reporting or searching the Schedule Database and IMS much
easier.
Document the BoE for the Activity Naming Convention
The P/p’s preferred approach for the activity naming approach in the IMS should be defined in the SMP
as part of the BoE. Consistency in the naming approach supports the alignment of the IMS with the
WBS. It also aids in traceability of activities for Assessment and Analysis, and the tracking of activities
for Maintenance and Control, and alignment of the IMS with the WBS.
5.5.6 Capture All Scope
It is a best practice for the schedule activities to capture all approved work scope, such that all work
can be allocated to complete the WBS elements in an integrated manner. It is critical that the IMS
contain tasks, milestones, and interdependencies logically sequenced in a manner that accurately
models the implementation plan for all approved scope from P/p start through completion based on all
P/p work as defined/broken down by the established WBS. Utilizing the WBS, as well as other P/p
87

sources of data, will not only help to ensure that the total scope of work is included in the schedule, but
also consistency in the integration of cost and schedule data.
A key consideration for capturing all scope in the schedule is making the schedule understandable and
easy to follow and use. While the content of each task in the schedule may be perfectly clear to the P/S,
it must also be absolutely clear to the PM, Technical Lead (e.g., WBS Element Owner/Control Account
Manager/Integrated Product Team Lead), and other P/p personnel (e.g., PP&C personnel). The phase
and maturity of a P/p often dictate how the scope is modeled in the schedule. Figure 5-15 provides an
overview of the expected schedule content and maturity at each phase of a Single-Project Program or
project:
Phase Expected Schedule Content and Maturity
Pre-Phase A Pre-Phase A schedules should include major development and integration milestones
representing: key milestones, project reviews, integration points, external and internal
Concept
interfaces or handoffs, and deliverables. Additionally, it is expected there should be high-level
Studies
summary tasks reflecting the general time-phasing estimated for developing system/mission
requirements, hardware design, fabrication, integration & test, and operational capabilities.
These early, high level summary estimates are typically derived from parametric models or
historical data from past similar projects. However, it should be noted that detailed information
should be available and included at a discrete and measurable level of detail for each concept
study that may be involved during this incremental phase.
Phase A Phase A preliminary schedules should have significantly more detail than the Pre-Phase A
schedules. During this phase of Formulation, the mission/system concept definition is
Technology
completed, most concept and trade studies are completed, preliminary requirements are
Development
established, and a preliminary Project Plan is developed. Therefore, project definition becomes
clear enough during Phase A to allow for a more discrete breakdown of work tasks and
milestones. Milestones should have predecessor and successor activities. A preliminary critical
path should be identifiable; there should be reasonable slack on the activities. Funded schedule
margin should be included, and resources should be identified. Additional unfunded margin
activities may also be included. The phased schedule should be synchronized with the project
phase budget. Preliminary requirements by subsystem, remaining trade studies, preliminary
and final design by subsystem, long lead procurements, preliminary systems engineering
products, preliminary safety and mission assurance products, fabrications by subsystem,
subsystem and system integration flow, subsystem and system testing, documentation
development, flight simulations software development and deliverables, hardware development
and test, test operations development for ground and flight should all be identified in the
schedule during Phase A.
88

Phase B Phase B is the final incremental phase of Formulation, which should produce the necessary
project definition to allow for discrete and measurable IMS detail, at least for the near-term of
Preliminary
six to twelve months. Near-term effort should be scheduled in meaningful tasks with shorter
Design and
durations. Durations not exceeding one month are preferable. IMS task detail down to the level
Technology
where work is discretely planned and measured at the lowest levels of the WBS and potentially
Completion
lower where necessary (i.e., subsystem, component, software function, test phase,
procurement deliveries, GFE deliveries, interface points, facility modifications, miscellaneous
documentation development stages, preliminary orbital debris assessment, etc.). A rolling wave
approach for planning the out-years may be used providing that the total scope of the project is
identified within the schedule and that all WBS elements are included. Durations for the out-
year planning phases can be further decomposed as the schedule matures. However, in cases
where far-term effort is well defined and task information is already available at the above
described low level of detail, then it should also be included in the IMS at the earliest
opportunity. Phase B schedule baselines are the foundation for measuring project schedule
performance throughout implementation. Reporting and other schedule management criteria
should be in place and in practice by the project. Regular status updates, reporting and
performance analysis should be taking place in the project office. The schedule should be
detailed enough to accommodate the collection of actuals (time and cost) at the appropriate
WBS level. The IMS will receive final baseline approval at the end of Phase B. The baseline will
then serve as the EVM performance measurement baseline.
Phase C Phase C is subject to the same guidance as Phase B. As time proceeds, far-term work tasks with
longer durations should be broken down into clearly defined and meaningful tasks with shorter
Final Design
durations (not exceeding one month, or potentially shorter). Special focus should be given to
and
providing clear schedule visibility into the completion of final design by specifying tasks and
Fabrication
“release milestones” for specific design or component-level drawings.
Fabrication tasks should clearly delineate the necessary work steps that reflect the planned
manufacturing work flow. IT development should clearly provide detailed tasks for software
functional design, code, debug, unit and integrated testing, software verification and validation,
IT hardware development, integration, and test. Specific tasks for Quality Assurance and buy-off
should also be clearly identified, as well as, orbital debris assessment baseline documentation.
Product delivery milestones from various fabrication process completions should reflect the
necessary handoff points to hardware assembly and systems integration.
Phase D The above Phase C guidance also applies to Phase D. Again, as time proceeds, far-term work
tasks with longer durations should be broken down into clearly defined and meaningful tasks
System
with duration lengths similar to those recommended in Phase C. Special focus should be given
Assembly,
to clearly defining the discrete flow of tasks necessary for requirements verification and for
Integration
hardware and software components to be assembled and then integrated into subassemblies,
and Test,
subsystems, and systems, reflecting the work required for final assembly, integration and test.
Launch and
Schedule detail for this phase should clearly delineate the necessary and measurable work steps
Checkout
that reflect the assembly, integration and test flow of work. Specific tasks for Quality Assurance
and buy-off, as-built hardware and software documentation, final systems acceptance reviews,
operations procedure finalization, and Operations training, and certification should also be
clearly identified. Specific hardware deliveries for Launch Operations activities should be
included. It should be noted that all pre-launch work should be verified and closed by the Flight
Readiness Review (FRR), which precedes KDP E.
89

Phase E The focus of the schedule for the incremental Phase E is the definition of tasks for execution of
the Mission Operations Plan: final verification and validation reports, flight readiness reviews,
Operations
final processing of launch hardware, ground operations, service preparation for launch, launch
and
activities through achieving operational orientation, or-orbit activities relating to mission
Sustainment
tracking, commanding, telemetry, trajectory, systems analysis, mission payload initialization
sustainment. Operations tasks with longer durations should be broken down into clearly
defined and meaningful tasks with shorter durations. Special focus should be given to clearly
defining the discrete flow of tasks necessary for Launch Operations and Sustainment.
Phase F The final phase, Phase F should also be defined in the same discrete and measurable level of
detail as described above. The focus of this incremental phase should address tasks such as: on
Closeout
de-orbit preparation and execution, abandonment of in-place flight hardware, recovery of
project assets, data/equipment disposition and storage, final environmental impact disposition
and resolution, lessons learned, contract closeouts, and final public education and notification
of reporting.
Figure 5-15. Relationship between the NASA life cycle phases and project schedule content.
Document the BoE for the Scope Included in the IMS
An important aspect of the schedule BoE is that it illustrates traceability to the complete P/p scope.
Documenting the source of information that serves as a basis for the content included in each IMS
element, most always the set of requirements set ratified by the P/p and its stakeholders, allows for
direct traceability to P/p requirements and assumptions. Source information pertaining to requirements
should be noted in the IMS’s notes field, the BoE itself, and within the SMP. As in 5.5.4, the quality of the
IMS’s connection to the P/p’s scope and requirements set should evaluated by executing the
Requirements Check assessment procedure, as described in Section Procedure 1. Requirements
Check6.2.2.1.1.
5.5.7 Develop Schedule Detail
It is a best practice for activities to be developed to the lowest level of detail appropriate, typically the
work package level, as early in the P/p life cycle as possible. It is a widely accepted theory that
advanced planning in the early stages of a P/p yield significant cost and time benefits when compared to
the original cost and time investment. Starting with the Cost and Schedule BoEs, the WBS, and the
Milestone Registry, all activities are loaded into the selected scheduling tool.
5.5.7.1 Define Work Activities and Milestones
The WBS is “decomposed” into discrete measurable tasks and milestones. It is a recommended practice
to input schedule data using a predominantly task-oriented (activities with durations) approach,
including milestones that are significant to the P/p. Activities should also be detailed enough so that
interface points can be clearly identified. These interface points, such as phase conclusions and
giver/receiver “handoffs”, are places in the schedule where milestones would be appropriate.
All identified milestones should be incorporated into the IMS. P/p notification and control milestones,
which are used as control points for work scope performance, are typically defined during pre-Phase A
in the Milestone Registry and may also be identified as events in the IMP, if it exists. The IMS should
always include a start milestone, which is a predecessor for the work activities at the beginning of a P/p,
90

as well as a finish milestone, which is the successor to all logic paths at the end of the P/p. Milestones
may also be used to identify major P/p events, such as LCRs, KDPs, or major test events. Contractual or
acquisition milestones (e.g., procurements, hardware deliveries, etc.), interface milestones, and
programmatic milestones should also be included in the IMS, if available. Locating P/p milestones at the
top of the IMS also helps to facilitate analysis. In most cases, milestones should be tied to or represent a
specific product deliverable or event and should have clear, objective (quantifiable) criteria for
measuring accomplishment.
It is necessary to keep in mind when developing the IMS, every schedule activity will eventually be
updated. The identified activities should facilitate the measure of progress. Schedule data that is task-
oriented lends itself to a more meaningful approach to monitoring task progress through the Schedule
Maintenance and Control process, as each activity is easily identifiable for updating purposes.
5.5.7.2 Define Level of Effort Activities
In addition to detailed activities and milestones, it is important to include tasks in the schedule that
represent support efforts (e.g., P/p management, systems engineering, safety and mission assurance,
etc.), which are typically referred to as “level of effort” (LOE) tasks. LOE tasks generally do not have
discrete products associated with their efforts but are seen as contributing to the comprehensive plan of
all work that is to be performed.45 LOE tasks often involve work that must be periodically repeated. The
duration of an LOE task is generally from the start to the finish of the work effort being supported. Thus,
an LOE activity will never add time to the P/p itself because it is dependent on the duration of the work
activity it supports. As such, an LOE task should never be on a P/p’s critical path. For EVM purposes,
LOE activities are measured “automatically by the passage of time” in terms of resources planned within
a given fiscal period.
5.5.7.3 Consider Schedule Size and Granularity
The overall size of the IMS depends on many factors, including the complexity of the P/p and its
technical, organizational, and external risks. In determining the appropriate level of schedule detail, it is
important to understand who the stakeholders are. Integrated schedules are crucial for all levels of
management oversight within NASA and its contractor community. The level of detail contained in the
schedule should also be a reflection of the intended use of the schedule. P/p schedules summarized for
management or presentations, as discussed in Section 5.6.2, may contain less detail than schedules used
by personnel performing the schedule activities such as procurement, design, fabrication, or testing.
Program Managers may require less detail for their evaluations than PMs. While it is true that all
Program work scope must be included within a Program schedule, the level of detail of the individual
project activities captured in the Program IMS may vary to accommodate the specific management
needs established at the Program level.
Generally, the greater the level of detail in a schedule, the greater the level of fidelity the schedule has.
In addition, more discrete task durations provide better insight into the real work integration points,
leading to increased accuracy in task sequencing and critical path identification, as well as increased
accuracy of progress measurement and IMS data credibility. The level of detail in the schedule can also
45 GAO-16-89G. GAO Schedule Assessment Guide. Page 14. December 2015. http://www.gao.gov/assets/680/674404.pdf
91

impact other P/p management process. Task-oriented activities should be sufficiently detailed to allow
for the practical establishment of defined finish-to-start network logic relationships. A lack of clear
understanding of the effort involved in each task can make Schedule Assessment and Analysis
cumbersome. However, using an excessive number of logical relationships to the same task or
milestone complicates schedule analysis.46
Consistency in activity granularity is also important. It is a recommended practice for a schedule to be
developed at a consistent level of detail. This allows PM to adequately plan the necessary resources and
to ensure adequate budget will be available to accomplish the work when it is planned. It also enables
greater decision-making capability related to discrete progress measurement, management visibility,
and critical path identification and control. However, consistency in granularity may be difficult to
achieve. Early in P/p life cycle, work is often based on high level assumptions because less detail is
available. In addition, whereas some Program schedules may be composed of aggregated project-level
milestones captured at a high-level and appear at a more consistent level of maturity throughout their
life cycle, project schedules tend to grow in maturity over time.
One exception to having consistency in schedule granularity occurs when it is important to know exactly
which detailed activities (and associated costs) are the most affected by risk and therefore constitute
the critical or driving paths. It a recommended practice that high risk and/or high cost areas within the
P/p should reflect more task detail within the IMS to support Schedule Analysis. Another example
would be the addition of tracking milestones that would be used in some of the performance
measurements. P/Ss should keep in mind that the level of detail used must lend itself to meaningful
cost/schedule and schedule/risk integration. It should also be noted that the level of schedule detail
may need to facilitate the type of EV measurement technique (e.g., 0-100, 50-50, weighted milestones,
percent complete, level-of-effort) that will be assigned in each earned value work package, which are
discussed in the NASA EVM Handbook. In addition, some placeholder activities that are not defined in
the WBS, nor captured in the BoEs, may need to be added to support other P/p process interfaces, such
as the Business Management System, EVMS, and Risk Management System or P/p-specific tracking
tools.
• Rolling Wave. Rolling wave planning, is a method that allows for scheduling to occur in waves,
through progressive elaboration, adding more detail as the P/p evolves and work activities
become clearer. The rolling wave method involves the use of both detailed and summary tasks
and can be applied to CPM scheduling. Rolling wave planning is useful when dealing with long
development or repetitive production schedules. It is also is widely used across NASA P/ps in
conjunction with EVM techniques, as illustrated in Figure 5-16.
46 PASEG, Version 3.0. National Defense Industrial Association (NDIA), Integrated Program Management Division (IPMD).
March 9, 2016. Page 61.
92

Figure 5-16. An example of the rolling wave planning approach used in conjunction with EVM.
When using the rolling wave method, near-term tasks (i.e., activities within 6-12 months of the current
date) are planned to a lower, discrete level of detail. It is a recommended practice for schedule activity
durations to be less than two times the update cycle (e.g., less than two months) for near-term
activities, as this allows for reporting of the start finish of an activity within one or two update cycles,
allowing management to focus on performance and corrective action if needed. Keeping durations to
two months or less will certainly benefit P/ps where EVM is being employed and should result in
increased accuracy in performance data. Tasks with durations longer than two months tend to make
measurement of objective accomplishment more difficult to assess accurately. Exceptions to this
recommended practice include procurement activities (e.g., long lead items) or level of effort (LOE)
activities (e.g., administrative support).47 This approach also enhances the P/S’s ability to more
accurately identify the P/p critical path.
Tasks that are scheduled to occur farther into the future should be included in the schedule but may be
planned at a more summary level of detail or planning package level. These summary tasks, while
reflecting less detail, should still provide enough definition of future work to allow for effective
identification and tracking of the P/p critical path or other driving paths. However, rolling wave planning
should not be used as a way around reflecting the most meaningful level of detail anywhere in the
schedule if the information is already known. Tasks should be developed to a discrete level of detail as
early as possible in the P/p life cycle to help to identify and mitigate P/p conflicts, risks, and problems.
This is particularly important for EVM purposes, as no Performance Measures are taken on planning
packages, only work packages. Durations should be revisited periodically as work progresses and as new
information becomes available. Thus, as future summary-level tasks (or planning packages) come into
the near-term window, they should be planned to a greater level of discrete and measurable detail and
incorporated into the IMS. In addition, the use of the rolling wave approach should be defensible and
supported by the BoE, since it is quite possible that future detailed planning will reveal situations that, if
known earlier in the P/p, could have resulted in more efficient and less costly work plans.
47 PMI. Practice Standard for Scheduling. Second Edition. Page 28.
93

Document the BoE for the Schedule Detail
While the level of detail in the P/p schedule should be as consistent as possible throughout, the
granularity may evolve as the P/p progresses through its life cycle. It is important to document the
expected schedule maturity and level of detail justification for each life cycle phase as part of the BoE. It
is also necessary to provide rationale in the BoE for any inconsistencies in the level of detail for schedule
elements, as lack of adequate detail in any area of the schedule may affect performance measurements,
critical path or driving path identification, or how uncertainty is applied when performing a schedule risk
analysis. This set of rationale should here be evaluated through the execution of the Critical Path and
Structural Check to the extent that elements of it pertaining to level of detail considerations can be
performed at this early stage. This aspect of the IMS is especially essential to its tractability; as such,
level of detail will be continuously scrutinized over iterations of the assessment, analysis, and control
processes. Assessment criteria for ensuring that the P/p has an appropriate level of detail can be found
in Section 6.2.2.2.1.
5.5.8 Logically Link the Activities
Logical relationships are critical to accurately modeling a P/p’s planned activities in the IMS. They
provide the dependencies between activities that help create the schedule network diagram, which
sequences the activities in a P/p across time. Understanding the dependencies between activities
usually starts with the development of summary-level flow diagrams, followed by assigning specific
activity relationships, paying special attention to avoid leads and lags and minimize activity constraints
unless necessary to represent particular activity-to-activity relationships.
5.5.8.1 Assign Activity Dependencies
It is a best practice for schedule activities to demonstrate horizontal traceability, such that they are
logically sequenced using proper relationship types that account for the interdependence of all
activities and milestones. Activities have dependencies upon one another. Activity relationships
provide the means to satisfy the need for horizontal traceability within the IMS. Establishing proper
dependency relationship-types is necessary to accurately model the P/p’s planned implementation.
Network logic must be complete, accurate, and realistic for horizontal traceability to help ensure the
ability to assess interim progress and forecast completion of key milestones and activities, as well as to
perform critical path analysis, as work is performed. A simple example is that one cannot roof a house
until the framing is complete. For a NASA spacecraft, the design is not started until the requirements
are completed.
There are a number of integration points within any P/p development flow, for example SDR, PDR, CDR,
SIR, Begin ATLO, etc. It is a recommended practice that summary-level flow diagrams be developed as
an aid to facilitate the assignment of schedule dependencies. Laying out summary-level flow diagrams
can help establish the flow of activities in early schedule development and is often employed before
schedule activities are developed to the lowest level of detail (Section 5.5.7). Flow diagrams are useful
not only as a guide for linking activities, but also as a communication tool to aid in the P/p’s
understanding and reporting of the activity relationships. Figure 5-17 is an example flow diagram from a
NASA project.
94

←←←←←←← B a tte ry
P D D U
P A P U
| C & D H  B o x 1  &  |  2p    |            |        |                      |     |     |
| -------------------- | ------ | ---------- | ------ | -------------------- | --- | --- |
| S tru ct a n d  p ro |  a ssy | ← N G IM S | ←← S o | la r A rra y  s (S A | )   |     |
H a rn e sse s
|             |     | ← P F P | M LI B | la n k e ts 1 |     |     |
| ----------- | --- | ------- | ------ | ------------- | --- | --- |
| F S W  4 .0 |     | ← R S   |        |               |     |     |
← E le ctra
|     |     | ← F S W  5 .0 |     |     | ←← M LI B la n k e ts 2 |     |
| --- | --- | ------------- | --- | --- | ----------------------- | --- |
F S W  6 .0
| P r o p  s y s ,  |     |     | S   | A  I& T | S V T s |     |
| ----------------- | --- | --- | --- | ------- | ------- | --- |
S h ip , C / O ,
| s t r u c t u r e ,  | S u b s y s t e m | s   P a y lo a d s   | E1 n v , S | V T s , S A   | O p t ic a l A lig n |     |
| -------------------- | ----------------- | -------------------- | ---------- | ------------- | -------------------- | --- |
D S N  E T E
| H a r n e s s ,  | I& T | I& T | st M | o t io n , T - | R e in s t a ll  |     |
| ---------------- | ---- | ---- | ---- | -------------- | ---------------- | --- |
M a t e
| A v io n ic s , I& T |     |     |     | V a c | In s t s , S p in | La u n ch |
| -------------------- | --- | --- | --- | ----- | ----------------- | --------- |
AS T LO
ta rt
|     |                                  |                                  |     | ← S T A | T IC |     |
| --- | -------------------------------- | -------------------------------- | --- | ------- | ---- | --- |
|     |                                  |                                  |     | ← S W   | E A  |     |
|     | ←←←←←←←←← ASSMRSTTS P P  B o o m | . P la tfo rm , H in g e , T A G |     | ← S W   | IA   |     |
|     | W E A  B o o                     | m , h in g e , R & R             |     |         |      |     |
u n  S e n so rs
|     | IM U s |     |     | R   | e fu r b |     |
| --- | ------ | --- | --- | --- | -------- | --- |
W A s
|     | ta r T ra ck e | rs  |     |     |     |     |
| --- | -------------- | --- | --- | --- | --- | --- |
W T A  1  &  2
|     | e le co m  P | a n e l |     |     |     |     |
| --- | ------------ | ------- | --- | --- | --- | --- |
D S T

Figure 5-17.  An example of a flow diagram showing where spacecraft, instrument subsystems and software drop into the
system integration and test flow.
Flow diagrams generally show major integration points and which subsystems and/or components flow
into them.  For example, in the first box on the left of the figure, the major structure and the propulsion
system are integrated.  Also included in that first step are supporting subsystems and subsystems
requiring early integration due to access problems.  After these subsystems are integrated, various tests
are performed.  Following that step, the remaining spacecraft subsystems and some of the instruments
are integrated and tested.  The process continues through the remaining steps.  These steps follow
repetitive cycles of “integrate then test”, culminating in the last step leading up to launch vehicle
integration and launch.
Once the overall workflow is sufficiently understood, activity dependencies can be assigned.  Every
milestone and activity in the schedule should have at least one predecessor and at least one successor
(i.e., no “open ends”).  Two acceptable exceptions are the P/p start milestone, which has no
predecessor, and the P/p finish milestone, which has no successor.  Another exception to this rule may
occur for activities or milestones that represent receivables or deliverables (Rec/Del) as described
below.  Any other instances only occur with valid reasons that are accurately documented.
Activities should also not be arbitrarily restricted but should be logically linked such that progress driven
effort determines remaining duration.  Predecessor and successor relationships should be appropriate
to the work needing performed and supported by the BoE.  Redundant links should be avoided since
they often confuse workflows and complicate analysis ((e.g., if Task A is linked to Task B, Task B is linked
to Task C, and Task A is linked to Task C, then the link between Task A and Task C is a redundant link.
Logic should never be assigned to summary activities, as summary Start and Finish Dates are derived
from the detailed activities.
95

Note: MS Project allows for two scheduling modes: “Manually Schedule” and “Auto Schedule”.
Manually Schedule is sometimes used for tasks lists or at the start of a P/p, when constraints or
predecessors/successors are unknown, but an output with an overview of key dates is desired.
Manually Schedule calculates the schedule based on dates entered by the P/S rather than the
predecessors and their constraints. Auto Schedule is where the benefits of the scheduling tool tie into
the Schedule Management process, as it considers the constraints and applies the logic to the
relationships entered by the P/S to calculate the schedule.
Receivables/Deliverables
Rec/Dels, also known as givers/receivers, formally document the schedule interfaces and handoffs of
critical items or products. The P/S may choose to maintain the Rec/Dels at a separate section near the
beginning of the IMS for easier visibility, as shown in Figure 5-18, or embedded in the workflow of the
schedule and supporting schedules, as sown in Figure 5-19 and Figure 5-20.
Figure 5-18. An example of a receivables/deliverables maintained near the beginning of the IMS.
96

Figure 5-19. An example showing Rec/Dels as they would appear within the workflow of a Single Consolidated P/p IMS.
97

Figure 5-20. An example showing a series of Rec/Dels as they would appear between multiple subsystems. Linked properly, the
Rec/Dels can ensure all work is accounted for from the Mechanical Subsystem, to Optics, and finally to Laser.
Level-of-Effort Activities
LOE activities require careful consideration when being linked in the schedule as to not drive discrete
work activities. LOE activities must be carefully modeled so that they do not inadvertently define the
overall length of the P/p and drive the critical path. “For example, P/S may choose to avoid the use of
logic links on LOE activities or they may create LOE activities that are one day shorter than the actual
planned P/p length. Because these techniques are used to circumvent the impacts of long-duration LOE
activities on traditional critical path calculations, their use and implications should be thoroughly
98

documented in the schedule narrative and BoE documents.”48 Nonetheless, hammock tasks can have
descriptions, codes, calendars, resources, costs and other attributes of a normal activity. Hammocks are
very useful for carrying time related costs and determining the duration of supporting equipment
needed for a P/p, as well as being used to create summary reports, which support Schedule
Communication.
Activity Relationships
There are four relationship models for the activities:
• Finish-to-Start (FS). The successor activity cannot start until the predecessor activity has
completed. This is the most common linkage because it follows the most common work flow;
complete an activity and hand off the work to the next activity. It is a recommended practice
that FS relationships be used as often as possible when establishing schedule logic. This
relationship provides for the most accurate calculation of total float.
• Start-to-Start (SS). The successor activity cannot start until the predecessor activity has started.
This relationship is used when two activities need to begin at the same time. This linkage is
commonly used at major integration points or at the beginning of the P/p. For example,
Authority to Proceed (ATP) may trigger the start of a large number of activities. In most cases
this relationship will be used with a lag value. Caution should be taken when using this type
relationship in lieu of breaking the effort down into more meaningful and discrete segments of
work that can more accurately represent the task sequence. Overuse and/or improper use of
start-to-start relationships will potentially hinder true critical path identification.
• Finish-to-Finish (FF). The successor activity cannot finish until the predecessor activity has
finished. This relationship is used when an activity needs to finish and provide something to
another activity so that it too can finish. Sometimes activities may need to be constrained to
finish at the same time because of a coordinated handoff of work to a successor activity. The
same caution as noted for start-to-start relationships also applies to the overuse and/or
improper use of finish-to-finish relationships.
• Start-to-Finish (SF). The successor activity cannot finish until the predecessor has started. For
example, the first step in the predecessor activity may generate a fit-check template needed
before the successor can start. This relationship is very uncommon, and caution should be
exercised before using this relationship to ensure its use is valid.
Figure 5-21 is a screen shot from MS Project showing examples of the four linking techniques and how
each impact the flow of the work.
48 GAO-16-89G. GAO Schedule Assessment Guide. Page 14. December 2015. http://www.gao.gov/assets/680/674404.pdf
99

Figure 5-21. Examples of the four activity logic relationships.
5.5.8.2 Avoid Leads and Lags
It is a best practice for schedule activities to only use lead and lag relationships when the values
represent real situations of needed acceleration or delay time between activities. A lag is a delay
inserted between activities that delays the start of a successor activity. Likewise, a lead allows a
successor to start before its predecessor has completed. A lead is the same thing as a negative lag.
Further definition of leads and lags is as follows:
• Lag. Lag time is the period of time applied to a relationship between two tasks that delays the
defined relationship execution. The amount of lag time (delay time) is assigned as a positive
value. For example, a task logically tied to another task with a finish-to-start relationship and a
5-day lag will result in the successor task’s start being delayed until 5 days after the completion
of the predecessor. Typical examples of lag time would be cure times on concrete pours and
bake-out times for conformal coating of printed circuit boards.
• Lead. Lead time is the period of time applied to a relationship between two tasks that
accelerates the defined relationship execution. The amount of lead time (acceleration time) is
assigned as a negative value. For example, a task logically tied to another task with a finish-to-
start relationship and a negative 5-day lead will result in the successor task’s start beginning 5
days prior to the completion of the predecessor. An example of using lead time would be where
the drawings review needs to start several days before the drawings are scheduled to complete.
Leads and lags often mask lower-level activities that should have been defined. Figure 5-22 provides an
example from MS Project showing how the leads and lags affect the successor-predecessor
relationships.
100

Figure 5-22. Example of the use of leads and lags as illustrated in MS Project.
There are instances where these types of relationships do exist and are reflected accurately by the
correct use of lag and lead times (e.g., cure times on concrete pours, bake-out times for printed circuit
board coating, and procurement order lead times). However, in most cases it would be preferable to
use an additional task, appropriately labeled, to represent the lead or lag time and to describe the
reason for the lag or lead (e.g., handoffs). This latter practice facilitates visibility and status updates and
would likely result in a more accurate and maintainable schedule. In other cases, it may be appropriate
to use a soft constraint. If using leads and/or lags, it is a recommended practice for justification to be
provided in the task notes or in a separately identified field within the IMS and/or Analysis Schedule.
Caution. Lead and lag times should only be used when these values represent real situations of needed
acceleration or delay time between tasks. Use of these techniques creates a maintenance issue should
the basis for the lead or lag time change. Lead and lag times are difficult to identify and document,
conceal actual activities that are not defined, and are often difficult to discern when analyzing a
schedule, as well as when performing an SRA or ICSRA. They may also corrupt float/slack calculations
and distort the critical path and driving paths. They also hinder the ability to capture EVM metrics (e.g.,
EVM cannot be taken against a lag because there is no scope associated with a lag).
5.5.8.3 Minimize Activity Constraints
A constraint is a fixed date assigned to a task to control when it starts or finishes. Caution should be
exercised when using constraints because they are a significant factor in how float (slack) is calculated
throughout the P/p schedule. While it is certainly true that there are various scheduling situations that
require the use of constraints to more accurately model the implementation plan (e.g., facility
availability, equipment availability, resource availability, vendor deliveries, etc.), careful thought should
be given that they are used appropriately.
It is a best practice for the schedule logic to limit the use of constraints other than As Soon As Possible
(ASAP) to situations that represent actual work flow. Soft constraints are preferable to hard
constraints or the use of leads or lags and may be used to delay the Start or Finish of a task because they
101

do not interfere with the logical flow of the schedule or the critical path calculations. For example, a
soft constraint might be used to delay the start date of a task to the expected availability date of data,
materials, or other resources that are not reflected in the IMS. Common soft constraint types that can
be imposed on an activity include, but are not limited to, the following:
• As Soon As Possible (ASAP). An Activity or Milestone will finish as early as possible based on its
assigned logical relationships and duration. This condition can also be described as the absence
of any constraint.As Late As Possible (ALAP)*. An Activity or Milestone will finish as late as
possible without affecting the schedule end date. It is a recommended practice that the ALAP
constraint never be used (specific to MS Project). This constraint uses total float to calculate its
Early Finish date instead of free float. This can cause the P/p end date to slip.
• Start No Earlier Than (SNET) or Start On or After. An Activity or Milestone will start no earlier
than the assigned start date. However, it can start as late as necessary. This constraint is often
used to phase the activities such that they align with budget allocation. Sometimes they are
also used to align the activities with the availability of a facility.
• Finish No Earlier Than (FNET) or Finish On or After. An Activity or Milestone will finish no
earlier than the assigned finish date. However, it can finish as late as necessary.
Hard constraints can prevent the logical flow of the schedule relationship logic, distorting the total float
(slack) and critical path calculations throughout the P/p. Hard constraints should be avoided except
where absolutely necessary. Instead, consider using soft constraints or deadlines. For awareness, hard
constraint types include:
• Start No Later Than (SNLT)* or Start On or Before. An Activity or Milestone will start no later
than the assigned start date. However, it can start as early as necessary. Finish No Later Than
(FNLT)* or Finish On or Before. An Activity or Milestone will finish no later than the assigned
finish date. However, it can finish as early as necessary. This is a useful constraint to use for a
contract deliverable milestone or P/p completion milestone.
• Must Start On (MSO)* or Start On or Mandatory Start. An Activity or Milestone will start on
the assigned date. Use of this constraint overrides schedule date calculations driven by logic,
resulting in a date that may be physically impossible to achieve.
• Must Finish On (MFO)* or Finish On or Mandatory Finish. An Activity or Milestone will finish on
the assigned date. Use of this constraint overrides schedule date calculations driven by logic,
resulting in a date that may be physically impossible to achieve.
Note(*): These types of constraints are often used as completion points in the schedule from which
the total float value is calculated. These constraints are often called “Hard Constraints” because
they can inhibit the correct time-phasing of the schedule. Improper use can cause negative float to
be calculated throughout the schedule.
Deadlines allow the P/S to place a target completion date on a task or milestone and do not interfere
with the logical flow of the schedule network.
• Deadline (MS Project only). While not listed as a constraint type, a deadline date assignment on
any task or milestone has the same results as assigning a “Finish No Later Than” or “Must Finish
On”, without compromising the ability for schedule logic to drive the schedule. Float (slack) is
calculated against the deadline date as if it were a “FNLT” or “MFO” constraint, generating
102

negative float when the task slips past it, but still allows for accurate critical path analysis
against important events in time. Figure 5-23 shows a deadline date represented by a
downward pointing green arrow. The finish milestone will be allowed to slip past it; the
deadline will not affect how the software schedules the tasks. However, total slack will be
calculated against the deadline date.49 P/S may choose to use deadline constraints in the
routine (e.g., monthly) schedule status update process to inform management of impending
issues, but deadlines should be removed from the approved IMS because of the hindrance they
may cause in identifying and managing the P/p’s true critical path.
Figure 5-23. Example of the use of a deadline date in MS Project.
Minimal use of constraints, other than ASAP, is strongly encouraged. Remember that constraints
override task interdependency relationships. Examples where constraints generally have a valid
purpose include the following:
• Assigning a “Start No Earlier Than” on a scheduled receivable from an external source
• Assigning a “Start No Earlier Than” when resources will not be available until a specified date
• Using a “Finish No Later Than” or “Deadline” on the final product deliverable or P/p completion
point
Constraints may also refer to limitations or conditions that affect the schedule. Typical examples of
these situations may include test facility downtime or unavailability of specialized computer
time/equipment. Take note that for schedules that are resource loaded, these situations are normally
best modeled through the use of resource calendars/assignments within the automated scheduling tool.
49 In MS Project should any predecessor push a task with a deadline that has zero slack, the task with the deadline will
automatically show up as “critical” in the Gantt chart. This can be useful for understanding when key tasks hit trigger target
completion dates.
103

Note: Different software tools may have different constraints or even different terminology to describe
constraints. Other tools have additional constraints such as Zero Total Float and Zero Free Float. While
these constraints may be necessary to reflect an actual work situation, they are the exception and not
the rule.
In summary, constraint use other than ASAP should be considered only when necessary to accurately
reflect the plan. When used, careful consideration should be given to which constraint type to apply.
The type of constraint will dictate the impact on float (slack) calculations for the task in question and
other tasks logically linked as successors. Furthermore, depending on the use, the proper calculation of
critical path may be hindered. If using leads or lags, or constraints other than ASAP, it is a
recommended practice to provide justification in the task notes or in a separately identified field within
the IMS.
Document the BoE for Schedule Logic
Ensuring proper logic between activities is essential to understanding the time phasing of work. As part
of the BoE, is important to document the rationale for non-standard dependencies between activities
(e.g., relationships other than Finish-to-Start), as well as the use of leads, lags, or constraints, to ensure
that the logic reflects the way in which the work is actually being performed. These departures from
standard schedule practice, documented within the BoE, will be examined in depth via the Health Check,
described in Section 6.2.2.1.2, and the Critical Path and Structural Check, described in Section 6.2.2.2.1,
the former of which should be performed continuously after the schedule logic has been established.
5.5.9 Estimate Activity Durations
Duration is the length of “working time” expected for an activity to complete (e.g., number of man-
hours), whether for a planning package or a work package. Activity duration may be dependent upon
the amount of resources applied/available, as well as the calendar applied to the activity. Having the
appropriate time units and calendars defined are necessary first steps so that the activity Start and
Finish Dates can be accurately calculated once activity durations are estimated and assigned in the IMS.
5.5.9.1 Define Time Units
It is a best practice for all activity durations to be scheduled according to the same time units. Prior to
assigning durations, a determination should be made as to the unit of measurement and level of
accuracy required. From a schedule analysis perspective, mixing time units within the same schedule
may result in slight differences and inconsistencies to float values internally calculated by the scheduling
tool. This result complicates the identification and analysis of a P/p’s critical path. Because of this, task
durations should generally be assigned in workdays except in cases where more detailed definition in
work hours is necessary. For example, short term, intense efforts (e.g. spacecraft vacuum testing, near-
launch activities, etc.), may require activities to be measured in hours. For a long duration plan, the
scheduler may round activities contained in the first year to the nearest day, and in subsequent years to
the nearest week or month, refining the estimates as the activity gets closer (e.g., spacecraft vacuum
testing). It is also important to establish whether activities will be measured by elapsed duration
(“edays”) or by the number of working days (“days”) and to be consistent throughout the schedule.
Elapsed duration allows activities to be calculated according to calendar days and ignores all non-
104

working time, such as weekends or holidays, per the P/p’s assigned calendar. In general, “days” is the
preferred time unit.50
5.5.9.2 Define Calendars
It is a best practice for activities to be scheduled according to representative calendars that
appropriately distinguish between working and non-working days. P/p calendars dictate working and
non-working times. Thus, the actual calendar-time for any activity is determined by using the work
hours and work days as defined by the assigned P/p calendar. Typically, P/p will have a default calendar
that defines the usual working and non-working periods for tasks or resources. However, it is
acceptable that customized calendars be established to allow activities or resources with different work
schedules to be more accurately planned. For instance, calendars may be different for each
organization, contractor, or resource working for the P/p. Calendars may also vary with phase and
activity. For example, some integration and testing activities are performed on a 24-hours per day, 7-
days per week (24/7) basis. Other activities or possible contingency situations may necessitate the use
of double shifts for a defined period of time.
If a P/p is resource loading the schedule, it may be necessary to use resource calendars, which specify
valid time units that a resource may be available to do work. Both resource and P/p calendars should be
used appropriately and be a key consideration when estimating task durations. When tracking costs
and/or EVM performance within the scheduling tool, it is a recommended practice that the P/p calendar
also be consistent with the accounting calendar to ensure accurate cost data. The P/S should be
cognizant of the impact on task scheduling and schedule analysis when both types of calendars apply.
Specific task and resource calendars should be established during initial schedule development.
Any of these customized calendars may be used throughout the P/p lifecycle, or intermittently, as
necessary. It is a recommended practice that customized calendars be clearly labeled and documented
with rationale as to any distinctions from the standard P/p schedule. Figure 5-24 is an example of a
work calendar extracted from MS Project.
50 GAO-16-89G. GAO Schedule Assessment Guide. December 2015. Page 65. https://www.gao.gov/assets/680/674404.pdf
105

Figure 5-24. Example of a work calendar extracted from MS Project.
Note: MS Project makes use of “elapsed days” or “edays”. When an elapsed duration is entered for an
activity, MS Project calculates the activity duration according to calendar days and ignores all non-
working time, such as weekends or holidays, per the P/p’s assigned calendar.
5.5.9.3 Derive and Assign Activity Durations
It is a best practice for schedule activity durations, including associated duration uncertainties, to be
derived based on sources and/or processes that are appropriate and provide the best justification for
their estimation. A key component of estimating schedule activity durations includes the use of
schedule estimating methods and models. Activity durations are sometimes determined solely by the
time “available” to complete the P/p. In this top down approach, a P/p’s terminal milestones are
derived from contractual, agency, congressional, or executive branch stakeholders. In this case, all other
schedule elements are also derived from these provided milestones, often embedding optimism into the
schedule prior to its development. This contrasts with the engineering build-up or unconstrained style
of schedule estimating that attempts to capture the entire work effort, as set forth by the requirements
set, and derive schedule element estimates without a final milestone target date in mind. Using
schedule estimating methods and models ensures that the dates in the schedule are determined by logic
106

and durations rather than by wishful thinking or estimates that are constructed to meet a particular
finish date objective.51 The P/S should remain diligent in collaborating with P/p teams, especially
Technical Leads, to determine the optimal basis rationale for each element. Documenting activity
estimate rationale also aids the P/p in preparing for P/p reviews.
5.5.9.3.1 Schedule Estimating Methods and Schedule Estimating Relationships (SERs)
The process for estimating schedule durations is often influenced by how much information is known
about the activity or set of activities in question. The selection of the schedule estimating method can
also often be tied to the schedule’s relationship with cost, data availability, estimate purpose, data
maturity, and P/p maturity levels. Some common methods and sources for deriving or verifying overall
IMS, lower-level subsystem, and/or individual activity duration estimates include the following:
• Established Standards. Well established, historically validated and recorded durations for
routine or procedurally-based activities or operations, such as hourly or daily rates per required
quantity.
• Brainstorming. P/p team members approximate durations based on a combination of factors
(e.g., expert judgment, prior experience, and historic actuals).
• Subject Matter Expert Experience and Judgment. Time estimates based on personal knowledge
and/or experience with the same personnel, or from similar P/p work or specialized training,
often guided by historic (actual) data. In cases wherein verified data contradicts expert opinion,
the burden of proof is on the expert to justify his or her judgment in light of the data.
• Analogy. Actual duration from similar activities (i.e., technical content) used as the basis for the
new activity duration, often adjusted for differences in complexity. Careful consideration should
be given to selecting the analogies. While the P/p can use any previous P/p as a relevant
analogy, the NASA OCFO maintains the SMART tool, which uses a parametric approach, to assist
in making this comparison for unmanned space flight missions. If the P/p is interested in a more
granular comparison other databases, such as the CADRe or the NASA Schedule Repository may
provide lower-level details. Furthermore, there may be generally accepted datasets for
particular elements of the P/p schedule that can be referenced for comparison.
• Parametric Analysis and Schedule Estimating Relationships (SERs). Calculated time estimates
derived from a mathematical relationship that defines schedule as a function of one or more
parameters for factors, which may include technical parameters (e.g., weight, power, mass, etc.)
as well as parameters for cost. Estimating schedule durations using a parametric approach
involves the same fundamentals as estimating cost. The quantifiable relationships between the
schedule and other P/p factors and influences can be captured as Schedule Estimating
Relationships (SERs) and then used to estimate durations of schedule events, much like Cost
Estimating Relationships (CERs) are used to estimate a particular price or cost. SERs are used to
51 GAO-16-89G. GAO Schedule Assessment Guide. December 2015. Page 65. https://www.gao.gov/assets/680/674404.pdf
107

estimate schedule duration by connecting an established relationship with one or more
independent variables to the duration time of an event.
Schedule duration data and independent variables are collected to conduct data analysis and
determine if there are statistically significant relationships present to produce an SER. If an
independent variable (driver) demonstrates a measurable relationship with schedule duration,
an SER can be developed. SERs can contain many of the same independent variables as Cost
Estimating Relationships (CERs) but could also be based on different datasets, normalization
techniques, or analysis methods. While relatively simple in concept, the ability to get accurate
and meaningful data that can be used to quantify a relationship between an independent
variable and schedule duration can be difficult.
Because of the fundamental relationship between P/p schedule behavior and cost behavior,
NASA offers a variety of cost-based databases, models, and tools, which contain schedule data
and/or SERs that can be used effectively for estimating schedule durations. Cost-based
resources are often a good source for parametric estimating of schedule durations, since the
IMS needs to correspond to cost estimates to ensure that enough resources can be applied to
activities to complete them within the expected duration. This should be done before the IMS is
baselined so that the relation between accurate cost and schedule estimates can be verified.52
• Extrapolations. Predicted time estimates calculated from existing known data relationships
and/or trends (e.g., 3-point time estimates).
• Build-Up/Bottom-Up/Grassroots. Decomposition of activities into lower-level tasks which are
estimated and then aggregated at higher levels. Using a detailed engineering build-up estimate
to develop a schedule estimate is a common technique. A highly detailed and logically linked
schedule is the standard product generated by this schedule estimation method. Grassroots
estimating for schedule requires strong attention to detail to be successful. Schedule Analysts
should continue to be careful when differentiating between a build-up schedule estimate and a
given detailed schedule plan. Both may employ the engineering build-up/grassroots approach;
however, there are significant differences. The former reflects an attempt to capture the entire
work effort to analyze durations and the program plan. A build-up schedule estimate, similar to
cost, is an attempt to predict the actual (i.e., actual duration/actual finish date.) The latter
reflects the result of a detailed P/p plan and may contain significant constraints, optimism, or
undocumented assumptions. The plan duration and plan finish date from a given detailed
schedule plan are attempts to organize future work with the goal of delivering on time.
• Performance-Based. Typically used for replanning or rebaselining purposes, actual P/p
performance such as task duration growth or milestone burndown can be used to estimate
schedule elements, via extrapolation or related techniques.
52 Additional information the relationship between cost and schedule can be found in NASA Cost Estimating Handbook, Version
4.0. February 27, 2015. Appendix K. Pages K-1 and K-2.
108

5.5.9.3.2 Schedule Estimating Databases, Models, and Tools
The following sections describe the available databases, models, and tools used by the NASA Schedule
Management community for schedule estimating.
Schedule Repository
In July 2019, NASA began an initiative to collect P/p schedules – IMSs in their native format files – in a
Schedule Repository.53 The purpose of the Schedule Repository is to formally archive P/p schedule data
on a regular cadence. The Schedule Repository also serves a useful database containing planned versus
actual schedule information over time. Once a P/p is complete, IMS files are made available to the
SCoPe for use in future P/p Schedule Development, including establishing activity duration estimates
and logic flows, as well as in Schedule Assessment, including performing comparisons of an IMS to
analogous P/p IMSs.
Cost Analysis Data Requirement (CADRe) and the One NASA Cost Engineering (ONCE) Database
CADRe provides a common description of P/ps at a given point in time. CADRe is a formally required,
three-part document that describes the programmatic, technical, LCC, and cost- and schedule-risk
information of a P/p at each LCR milestone (SRR, PDR, CDR, SIR, Launch, End of Mission). 54 Both cost
and schedule analysts can develop better estimates of future P/ps by using CADRe to pull historical
records of cost, schedule, and technical attributes for analogous P/ps. CADRe data is also used to
populate the Master List of P/p Schedules and can help analysts generate a variety of Schedule Outputs,
as shown in Figure 5-25.55
53 Agency Policy Guidance to Enhance Earned Value Management (EVM) and Create a Schedule Repository. June 4, 2019.
https://community.max.gov/display/NASA/Schedule+Community+of+Practice
54 CADRe/ONCE – Data Collection and Database.
https://www.nasa.gov/offices/ocfo/functions/models_tools/CADRe_ONCE.html
55 NASA’s Master List of Project Schedules is maintained by OCFO’s Strategic Investment Division and can be requested through
SCoPe, hq-scope@nasa.gov.
109

Figure 5-25. Examples of reports that can be manually generated from CADRe data.
Automated search and query of CADRe information is available via the One NASA Cost Engineering
(ONCE) Database.56 ONCE is a web-based database that provides controlled access to the CADRe data
and information. The data stored in ONCE mimics the CADRe templates - Parts A, B, and C. Since
CADRes represent snapshots of a P/p at successive key milestones, the ONCE Database captures all the
changes that occurred to previous P/ps and their associated cost and schedule impacts.57
Schedule Management and Relationship Tool (SMART)
The SMART, which is available on the ONCE Model Portal, combines analogy-based and parametric
methods in a schedule estimating tool for unmanned, Category-1 spacecraft P/ps from Authority to
Proceed (ATP) to Launch.58 The tool utilizes high-level technical and programmatic characteristics to
determine a spacecraft’s likely development schedule duration. Based on the spacecraft parameters,
56 ONCE. https://oncedata.hq.nasa.gov
57 One NASA Cost Engineering (ONCE) Database. https://oncedata.hq.nasa.gov/
58 Schedule Management and Relationship Tool (SMART) can be accessed on the ONCE Database,
https://oncedata.hq.nasa.gov. The creation of SMART resulted from an Office of Evaluation (OoE) research study in 2014.
Analysts with questions about using SMART for SER capability should refer to
www.nasa.gov/offices/ocfo/functions/models_tools/smart.
110

SMART produces a cumulative distribution function (CDF) that reflects the durations of the analogous
missions. It also illustrates the confidence level of the P/p’s estimate for further comparison. SMART
incorporates NASA Schedule Estimating Relationships (SERs) for another point of comparison. Unlike
other third party SERs, those within SMART are derived from a strictly NASA population for a more
applicable assessment and comparison. The SMART can also help identify which spacecraft parameters
are contributing factors to longer durations. SMART SER’s schedule drivers (parameters which are highly
correlated with schedule) include: mass, power, mission design life, year of development, number of
instruments, mission class, and maximum data rate. SER’s are developed for development life cycle as
well as intermediate milestones (e.g. SRR to PDR). Figure 5-26 shows an example of SMART inputs and
outputs.
Figure 5-26. Example of a SMART inputs and outputs.
111

NASA Instrument Cost Model (NICM)
Another NASA modeling tool that contains schedule data and SERs is NICM.59 NICM, which is available
via the ONCE Model Portal, focuses specifically on instrument estimation and contains a large database
of many different types of instrumentation.60 This database includes schedule data, and there is a
component within NICM for estimating schedule duration using SERs. The NICM approach to calculating
duration from SERs is unique in that cost is an input to the SER equation. In this way, NICM SERs
establish a functional link between the calculated cost of an instrument and its schedule duration. In
addition to utilizing Cost As an Independent Variable (CAIV), NICM relies on the mission type and
instrument subtype in the SER equation. Figure 5-27 shows the NICM model schedule equations.
Additional information on the instruments used in each SER can be found in the NICM User Guide.61
Figure 5-27. NICM SER equations.
5.5.9.3.3 Activity Durations
When determining activity duration estimates, it is a recommended practice that the optimistic duration
(best case), the most likely duration, and the pessimistic duration (worst case) estimates (i.e., duration
parameters) are collected based on the inherent duration uncertainty of the activity along with
supporting rationale for each value. These values are often captured as minimum, most likely, and
maximum (Min, M/L, Max). By considering the possible best case and worst-case durations, the intent is
to capture the range of the activity duration uncertainty so that it can be modeled to reflect all possible
outcomes. In cases where the duration of a task is very well defined and historically substantiated, the
Min, M/L, Max estimates may be the same, or nearly the same value. Examples of this scenario may
include the duration estimates for off-the-shelf procurements, standardized testing, and P/p reviews. In
these situations, an uncertainty estimate may not be necessary. A key principle to remember is that the
P/p team member who has the assigned responsibility for a task must also maintain ownership of the
59 Analysts with questions about using the NICM for SER capability should contact Joe Mrozinski of the NICM development team
at the Jet Propulsion Laboratory (JPL), at jmrozins@jpl.nasa.gov.
60 NICM can be accessed on the ONCE Model Portal, https://oncedata.hq.nasa.gov.
61 “982-0000 Rev. 8. NASA Instrument Cost Model (NICM) Version VIIIc.” July 2018. Jet Propulsion Laboratory, California
Institute of Technology. For more information, contact NICM@jpl.nasa.gov.
112

schedule for accomplishing that task. This includes their review and approval of the durations contained
in the schedule. Thus, durations should not be padded in order to keep a hidden cushion, reduced to be
unrealistically optimistic, or arbitrarily cut by management.
It is also helpful to know what labor resource skills are available and the experience levels of those skills
to be assigned. An inexperienced technician or crew, for example, may take longer to perform the task
than an experienced technician or crew. While equipment resources are reusable, they may not always
be available during the time needed. Consumable resources must be closely monitored and replenished
as needed to support schedule needs. All of these factors may not be known at the time of making the
initial duration estimate for a task, but they are all considerations that may be used to later adjust a
duration estimate, once their impact is known. In addition, labor and financial reports, reflecting actual
hours and dollars from prior periods or previous P/ps, may also provide helpful information for
estimating durations. These reports provide historical data that can be used for both initial and
replanning efforts which involve work scope that is similar to previous activities or past P/ps. The P/S
must constantly be vigilant in establishing and maintaining a P/p schedule that is current and accurate to
help mitigate resource problems.
Figure 5-28 shows the durations loaded in the schedule after all attributes related to estimating the
durations have been considered.
Figure 5-28. Documented basis for durations in the IMS.
Document the BoE for Activity Durations
It is highly likely that a P/p schedule will be derived using multiple estimating techniques. Therefore, it is
important to document the basis rationale for schedule estimating techniques and estimates themselves
for each element of the schedule as part of the BoE; primary data used should also be included in the
BoE Dossier, which should be evaluated continuously using the Basis Check assessment process after
task durations are initially determined.
113

5.5.10 Identify the Critical Path(s)
It is a best practice for the P/p’s critical path(s) to be clearly identifiable within the schedule
throughout the P/p life cycle. In CPM scheduling, the critical path is generally defined as follows:
• Critical Path. A sequential path of activities in a network logic schedule that represents the
longest overall duration from the status date through P/p completion, which determines the
shortest possible P/p duration (i.e., least amount of float) and earliest possible P/p finish date.
Any slippage of the tasks in the critical path will increase the P/p duration and slip the P/p finish
date.
CPM is also used to determine the amount of flexibility, or float, in each of the logic network paths.
There are two types of float (slack) common to most scheduling tools:
• Total Float. The amount of time that a task or milestone can slip before it becomes part of the
critical path. Total Float directly relates each task to the P/p end date.
• Free Float. The amount of time a task or milestone may move into the future from its early
finish date before affecting its immediate successor task(s).
The concept of float is further discussed in Section 5.5.11.
Given the basic principle that each activity will finish before its successor begins, CPM calculates the
longest path of planned activities to logical end points or to the end of the P/p, and the earliest and
latest that each activity can start and finish without making the P/p longer. The calculations are done by
way of a “forward pass” and “backward pass” without regard for resource requirements/constraints.
This automated process determines which activities are "critical" (i.e., on the longest path, usually a
zero-float path) and which have "total float" (i.e., can be delayed without making the P/p longer).
It is important to note that if the terminal milestone of the P/p has a hard constraint date assigned to it,
then the critical path could have a positive or negative total float value instead of zero. Figure 5-29
shows an example of a P/p’s critical path calculated from total float.
114

Figure 5-29. An example showing the critical path based upon total float (i.e., slack).
It is important to note that unless the IMS represents the entire scope of effort and the effort is
correctly sequenced through the logic network, the scheduling software will report an incorrect or
invalid critical path (i.e., the critical path will not represent the activities affecting the P/p finish date).62
Accurate float values can only be determined if a complete and valid network logic is in place. Figure
5-29 shows an example project schedule that shows the critical path based on the total float calculation.
For most NASA Space Flight P/p’s, “P/p completion” may mean “launch” in the context of calculating the
critical path. For Research and Technology P/ps, it may mean the delivery of an end-item, such as a
technology demonstration or an analysis report.
There is an important difference between critical path activities and “critical activities” as potentially
characterized by P/p management. In strict scheduling terms, the critical path is the sequence of
activities that are tied together with network logic that have the longest overall duration through P/p
completion, whereas a “critical activity” is often treated as a task which has been subjectively deemed
important enough to have this distinction assigned to it. For example, KDPs, the development of a
primary system component, important tests, or other high-risk technical activities may be considered
“critical activities.” However, these activities are not always on the P/p’s critical path as calculated by
62 GAO-16-89G. GAO Schedule Assessment Guide. Page 1. December 2015. http://www.gao.gov/assets/680/674404.pdf
115

the scheduling tool.63 If the P/ps want to track the most “critical” paths to interim milestones of
importance, these are identified as driving paths, as follows:
• Driving Path. The critical path to an end item other than P/p completion. It is based on zero
free float identifying the drivers to any activity, rather than the effect on total float.
It’s a recommended practice that the P/p identify near-critical and driving paths throughout the P/p
lifecycle. A P/S can identify these near-critical or driving paths by isolating the sequences of activities
that have less than some minimum threshold value of total float, as determined by the P/p management
The number of paths identified usually depends on how “near critical” each path is; although, it is
common practice to track the primary, secondary, and tertiary critical paths, at a minimum.
Document the BoE for the Scheduling Method
Proper horizontal traceability and validation of proper schedule dynamics via the Shock Test, described
in Section 6.2.2.2.1, directly enable verification of terminal milestones’ critical paths (and interim
milestones’ driving paths). This is a perquisite for properly identifying a schedule’s critical paths, which
enables understanding the various cascading effects of any task’s or milestone’s movement within the
schedule network, determines the earliest schedule completion date, and focuses the P/p team’s energy
and management’s attention on the activities that will lead to the P/p’s success.64
5.5.11 Establish and Allocate Margin
It is a best practice for adequate margin to be established and allocated as part of the schedule
baseline and clearly identifiable. At this point in schedule development, the IMS contains all activities
needed to complete the total P/p scope of work and deliver the final product. All activity relationships
are defined through the linking of the predecessors and successors. Constraints and durations are
assigned to all activities. Although the scheduling tool has all that is needed to time-phase the activities
and calculate a completion date based on the P/p scope, there remain a few more things that need to
be done to make the IMS complete. Margin needs to be added based on quantified risks and
uncertainties and phasing needs to be considered to make the schedule compatible with the available
resources.
In order to establish and allocate margin, it is important to understand what margin is and how it differs
from other schedule resiliency approaches, such as the use of contingency and float. Within the context
of Schedule Management, the following definitions for schedule resiliency are used:
• Schedule Margin. Schedule margin is a separately planned quantity of time (working days)
above the planned work duration estimate to be used specifically to address/absorb the impacts
due to risks and uncertainties.65 It is a risk-informed duration that is included as “activities” in
the schedule prior to baselining. Margin is intentionally loaded in the IMS just like any other
63 “Concurrently Verifying and Validating the Critical Path and Margin Allocation Using Probabilistic Analysis.” Joint Space Cost
Council (JSCC) Scheduler’s Forum. Page 3. March 2017.
64 GAO-16-89G. GAO Schedule Assessment Guide. Page 75. December 2015. http://www.gao.gov/assets/680/674404.pdf
65 NPR 7120.5E, page 56, defines Margin as, “The allowances carried in budget, projected schedules, and technical performance
parameters (e.g., weight, power, or memory) to account for uncertainties and risks. Margins are allocated in the formulation
process, based on assessments of risks, and are typically consumed as the program/project proceeds through the life cycle.”
116

activity; however, these activities do not have any defined scope, nor do they have any
associated budget.
Note: Some organizations may use terms such as “reserves” or “integrated returns” to describe
schedule margin, however the NASA preferred terminology is “margin.” Reserve is often used
to refer to forms of funding (e.g., Management Reserve)66; however, NPR 7120.5 specifically
states that “reserve” is an obsolete term and makes references instead to “schedule margin” for
schedule and “UFE” for funding.
• Contingency. Within the context of Schedule Management, Contingency refers to non-working
days or times in the schedule (such as holidays, weekends, or extra shifts) that could be used to
overcome performance delays.
Note: Contingency is not to be confused with margin (i.e., working-days) that are intended for
use to overcome uncertainties and risks.67
• Float or Slack. In general terms, float is the number of workdays that an activity can be delayed
without impacting the start of a later activity. Float is an automatic calculation performed by
the scheduling tool using CPM scheduling. It is calculated by subtracting early dates from late
dates (i.e., Float = Late Dates - Early Dates). A CPM schedule critical path is typically
characterized as the path with the least amount of total float. Calculating the float in the
schedule is particularly important for the space community because spaceflight missions are
often constrained by launch dates, which limits the amount of available time in the schedule
and makes the flexibility to revise various workflows more important with respect to managing
risks. Float informs management as to which activities can be reassigned resources in order to
mitigate slips in other activities. Because float is a calculated value, it can be either positive or
negative, but the intent is to plan the P/p work such that the schedule has either positive or zero
float on the critical path. In general, negative float arises when an activity’s completion date, or
associated milestone, is constrained—that is, when the constraint date is earlier than an
activity’s calculated late finish. In essence, the constraint states that an activity must finish
before the date the activity is able to finish as calculated by network logic. Date constraints
causing negative float need to be justified or removed. Zero float is an indication that an activity
delay of a given number of days will result in a P/p delay of the same number of days. There are
two types of float: Free Float and Total Float.
• Free Float (Free Slack). Free float refers to the amount of time a task can be delayed before
impacting the early start date of its immediate successor(s). Zero Free Float is typically used to
model “just-in-time” deliveries by making early dates equal to late dates (i.e., scheduling
activities according to the late date), forcing the schedule to become equal to the “late
66 Per NPR 7120.5E and the NASA Space Flight Program and Project Management Handbook, SP-2104-3705 “reserves” is an
obsolete term that has been replaced by “Unallocated Future Expenses (UFE)”. However, a more general use of “reserves”
tends to appear in terms of “cost reserves” held by the CAMs or PM on a given P/p and does not necessarily refer to Mission
Directorate-held UFE. https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/20150000400.pdf
67 Whereas NASA differentiates between “margin” and “contingency”, GAO uses the terms interchangeably with respect
schedule margin.
117

schedule”. Zero Free Float can make an activity critical if the Free Float and Total Float are equal
(i.e., applying Zero Free Float constraints consumes all activities free float as well as all activities
total float, making them all critical).
• Total Float (Total Slack). Total Float is the amount of time an activity can be delayed before
impacting the overall P/p completion (i.e., P/p critical path, finish date or end-item date). Total
Float directly relates each task to the P/p finish or end-item date. Positive Total Float is an
indication that an activity can be delayed without affecting the P/p completion. Negative Total
Float is an indication that an activity will impact the P/p completion unless the time is
recovered. Zero Total Float is an indication that an activity delay of a given number of days will
result in a P/p delay of the same number of days.
It is important that the appropriate terms be used consistently across all P/p elements, such that
assessment of the P/p’s flexibility and ability to overcome or mitigate uncertainties and risks is easily
identified and well understood. Whereas float is directly related to the logical sequencing of activities,
margin is established through an understanding an analysis of P/p uncertainties and risks.
5.5.11.1 Key Guidelines for Incorporating Margin
When incorporating margin into the schedule, there are key guidelines that should always be addressed
and maintained throughout P/p Implementation:
• Margin should be established and allocated throughout the schedule to aid in the management
of uncertainties and risks
• Margin should always be identifiable in the schedule
• Margin should be managed and controlled by the PM
• Adequate amount of budget (dollars) must be available to cover the added margin duration
Section 7.3.2.1.4 discusses the processes for the management of schedule margin.
5.5.11.2 “How Much” Margin to Establish
Just as activity duration estimates can be based on other sources of information, early in P/p
Formulation, it is a recommended practice that schedule margin estimates be informed by analogous
missions, expert experience and judgement, or established standards. Example guidelines for
established standards consolidated from several NASA Centers are shown in Figure 5-30.
From (Point in Life Cycle) To (Point in Life Cycle) Amount of Planned Margin
Confirmation Review Beginning of Integration & Varies: 1-2 month of schedule margin per year
Test
Start of Integration & Test Shipment to Launch Site Varies: 2-2.5 months of schedule margin per year
Delivery to Launch Site Launch Varies: 1 day per week, 1 week per month, 1
month per year
Figure 5-30. Established standards for margin allocation.
These margin guidelines are suitable for early P/p planning; however, margin task durations can also be
established in a way that corresponds to the likely impact of the P/p’s associated uncertainty and risk
118

based on the results of a probabilistic analysis. As early in the P/p life cycle as possible, margin
durations should be demonstrated to be adequate using some form of risk analysis (see Best Practice in
Section 6.3.2.5.3.6). Per NPR 7120.5, “margins are allocated in the Formulation process, based on
assessments of risks, and are typically consumed as the P/p proceeds through the life cycle.”68 Figure
5-31 shows the NPR 7120.5 requirements for risk-informed schedules. Furthermore, the NASA Cost
Estimating Handbook characterizes a risk-informed schedule as having discrete risks and uncertainties
accounted for within the schedule.69
Figure 5-31. The requirements for risk assessments and risk analysis by project phase are listed in this figure.
Early in the P/p life cycle, it is a recommended practice to perform a probabilistic schedule risk analysis
to inform the adequacy and placement of schedule margin in the IMS. The amount of margin
incorporated in the schedule should be enough to accommodate all identified duration uncertainties
and discrete risks. Developing informed duration uncertainties requires that the P/p have a clear
understanding of whether its task duration estimates are accurate, inflated, or overly optimistic. It is
also important for the P/p to be aware that unexpected events may occur, which may cause the
schedule to slip (e.g. extreme inclement weather, government shutdown, etc.). Discrete risks are
identified through the P/p’s Risk Management process, the likelihood and impacts of which should be
68 NPR 7120.5E. NASA Space Flight Program and Project Management Requirements. Effective Date: August 14, 2012.
Expiration Date: August 14, 2020. Page 56.
69 NASA Cost Estimating Handbook, V4.0. Appendix J. Page J-7. February 2015.
https://www.nasa.gov/sites/default/files/files/CEH_Appj.pdf
119
ytirutaM
dna
delpuocnU
delpuoC
ylthgiT
delpuoC-ylesooL
stcejorP
detnemucoD
detnemucoD
enilesaB
enilesaB
S R
P re lim
S R R
P re -P h a s e A
K D P A
M C R
R is k
in fo rm e d a t
p ro je c t le v e l
w ith
p re lim in a ry
P h a s e D
c o m p le tio n
ra n g e s .
F o rm u la tio n
R S D
in a ry B a s e
S D R
P h a s e A
K D P B
S R R S D R / M D R
R is k R is k
in fo rm e d a t in fo rm e d a t
s y s te m le v e l s u b s y s te m
w ith le v e l w ith
p re lim in a ry p re lim in a ry
P h a s e D P h a s e D
c o m p le tio n c o m p le tio n
ra n g e s . ra n g e s .
IM S .
lin e
K D P 1
P h a s e B
K D P C
R is k -
in fo rm e d
a n d c o s t- o r
re s o u rc e -
lo a d e d .
IM S .
C D
K D
P h a
K D
C D R
Im p le m e n ta
K D P I
P IR
P II K D P III
S IR O R R M R
U p d a te U p d a te U p
s e C P h a s e D
P D K D P E
S IR O R R M R
U p d a te U p d a te
tio n
R / F R
d a te
R / F R
P hK aDD sPR
P IR n
D R
e E P h a s e
F
D R R
F

discussed among the PM, Technical Lead, Risk Manager, Business Manager, and Scheduler. Considering
the results of an SRA that incorporates both uncertainties and risks allows for increased accuracy in
downstream forecasts. In addition, NPR 7120.5 requires a risk-informed schedule at the project level at
KDP A, a risk-informed schedule at the system level at SRR, and a risk-informed schedule at the
subsystem level at SDR, which are typically achieved through an SRA. Details on performing an SRA,
including determining the uncertainty and discrete risk parameters to include in the SRA Model, are
contained in Section 6.3.2.5.3.
An ICSRA/JCL is required at KDP I/KDP C just prior to setting the P/p baseline, as well as at rebaselines
for tightly coupled programs, single-project programs, or projects with an estimated LCC greater than
$250 million. For single-project programs and projects with an LCC of $1 billion or more, an ICSRA/JCL is
required at KDP B, CDR, and KDP D.70 During Implementation, it is important to take P/p float into
consideration when establishing any new margin activities due to a better understanding of
uncertainties or the identification of new risks. For instance, it is likely that the P/p has little flexibility in
changing its finish date or end-item delivery date. It is also possible that the P/p has already identified
margin in an amount equal to the available total float during the initial Schedule Development process.
If not, the P/p may opt to take the remaining amount of days between the calculated early finish date
and the P/p’s finish date (which should be represented by total float) and add a margin activity that
applies an equivalent duration in the schedule to absorb any remaining float. This will make the primary
critical path a zero-float path and maximize the amount of margin the P/p has available to manage
identified risks and uncertainties. If more margin is allocated than total float in the schedule, the float
on critical path activities will become negative, indicating that the P/p requires time beyond its
scheduled completion (see also Section 1.1.1.3, At the End of the Schedule Logic Flow).
This handbook places emphasis on identifying and managing schedule margin over float. With margin, it
is possible to determine whether a P/p has “adequate” margin due to its direct relationship to
uncertainties and risks. Managing margin allows for direct traceability to potential uncertainty and/or
risk impacts. Because the allocation of margin requires available float in the deterministic schedule, by
managing schedule margin, the float is often managed by default. Guidance on margin and float erosion
tracking can be found in Section 7.3.3.1.6.
5.5.11.3 “Where” to Allocate Margin
Schedule margin must be introduced into the schedule at strategic locations so that it can effectively
satisfy its intended purpose to absorb or mitigate risk and be easily accounted for as part of the critical
path sequence.
Where Risks Occur
Deliberate locations for margin include placement along the critical path where risk impacts are
expected to occur. Risks may also be identified on paths other than the deterministic, primary critical
path. For instance, it is common to allocate margin to more than one development activity, usually
along the primary, secondary, and tertiary critical paths, which are often risk-informed driving paths. A
driving path is the longest path to an end item, such as a milestone or delivery, other than P/p
70 Memo from the NASA Associate Administrator: “Joint Cost and Schedule (JCL) Requirements Updates.” May 24. 2019
120

completion. A driving path is based on the zero free float identifying the drivers to any activity, rather
than the effect on total float to P/p completion. Margin activities can be captured on these paths as
well for better management insight and schedule control; however, margin calculations against the
overall P/p finish date or end-item delivery date should be derived from the P/p’s primary critical path
for reporting purposes.
In general, for Space Flight P/ps, margin can be assigned to systems and subsystems during design and
fabrication and placed just before delivery into I&T in order to protect the start of I&T. After I&T start,
additional margin tasks are assigned throughout the I&T flow and are usually placed just before major
test activities to protect time slots in the test facilities. At the end of I&T, another margin task is usually
assigned to protect the ship date to the launch integration activity. Of course, there are variations on
this approach depending on the actual P/p Planning (e.g., performing an SRA to establish risk-informed
margin locations as described in Section 6.3.2.5.3.6).
Figure 5-32 is an example of margin allocation for a project early in Formulation using established
standards. The margin from the subsystems into the Integration and Test (I&T) as shown here is a single
margin allocation.
Figure 5-32. An example of margin allocation using established standards.
Prior to Key Milestones/Events
Margin tasks may be placed just prior to key milestones or events, such as: significant assembly,
integration, and test (AI&T) milestones, contractual milestones, or lifecycle review milestones. The
duration of these types of margin tasks can be based on uncertainties in the schedule elements leading
up to those key milestones or events. For example, more margin might be attributed to critical areas of
the schedule where tasks carry higher uncertainties, whereas less margin might be attributed to less
121

“risky” areas of the schedule. It is important to note that schedule margin durations should not be used
to hold a deliverable forecast to a static date but should be based upon risks and uncertainties.
Prior to End-Item Deliverables, Contract Completion Milestone, or P/p Finish Milestone
It is a recommended practice that some margin be placed at the end of the schedule network logic flow
just prior to the appropriate set of end-item deliverables, P/p or contract completion tasks, or P/p finish
milestone. For spaceflight P/ps, the work near the end of the schedule becomes more serial or single-
flow in nature and realized risks tend to be more problematic because of decreased flexibility in the
schedule to incorporate workarounds.71 However, P/ps should use caution when applying margin near
the end of the P/p. P/p teams may interpret a lump sum of margin at the end of the schedule as being
“up for grabs” to cover late activities. The intent of margin activities should be made clear; it is not to be
consumed due to performance delays, rather any margin near the end of the schedule should be closely
managed and used strategically to absorb any late risk impacts or implement risk mitigations. Should
performance delays occur, Technical Leads may need to work weekends or extra hours to finish on time
versus using margin.
5.5.11.4 Consider Budget for the Eventual Use of Margin
Margin is identified for future situations that are not clearly defined, such as potential risks and
uncertainties, where there is no known or approved P/p scope involved. The use of margin will likely
and eventually require the allocation of budget (dollars), either when risks are realized, or risk mitigation
activities are identified, and the associated scope is added to the baseline plan. It is very important that
an adequate, estimated amount of budget be “available” to cover a reasonable workforce level through
the duration of the schedule margin activity, should the P/p need to “use” the margin.
It is possible that budget needed to support the new scope will either come from either P/p-held
Management Reserve (MR) or NASA HQ-held Unallocated Future Expenses (UFE).72 Because UFE is
generally risk-informed as part of a risk analysis exercise to set the Agency Baseline Commitment
(ABC)73, it is likely that UFE will exist in an amount to cover the projected risks that may affect the
schedule.74
It is a recommended practice that no specified budget be assigned to a schedule margin activity as part
of the baseline. Instead, budget available for “planned” schedule margin activities should be maintained
outside of the baseline. As part of the SRA activity, this may be handled by creating a discrete risk in the
71 “Concurrently Verifying and Validating the Critical Path and Margin Allocation Using Probabilistic Analysis.” Joint Space Cost
Council (JSCC) Scheduler’s Forum. Page 16. March 2017.
72 Per the NASA EVM Implementation Handbook (NASA/SP-2018-599), ANSI/EIA-748 provides for the establishment and use of
MR to handle risks (and uncertainty). https://www.nasa.gov/evm/handbooks
73 NPR 7120.5E, page 52, defines Agency Baseline Commitment as, “Establishes and documents an integrated set of project
requirements, cost, schedule, technical content, and an agreed-to JCL that forms the basis for NASA's commitment to the
external entities of OMB and Congress. Only one official baseline exists for a NASA program or project, and it is the Agency
Baseline Commitment.”
74 “The level of UFE or UFE percentage should be selected based upon achieving a particular level of confidence from the cost or
joint cost and schedule risk analysis. The appropriate level of confidence is chosen by the appropriate NASA management
council after the analysis, and the resulting UFE should be identified as the recommended level at all Confirmation Reviews.”
NASA Cost Estimating Handbook, V4.0. Page 28. February 2015.
https://www.nasa.gov/sites/default/files/files/01_CEH_Main_Body_02_27_15.pdf
122

risk list, mapping it to a margin activity assigned at the appropriate point in the schedule, and then
putting a lien against the MR or UFE until the margin is “used” – that is, converted to an activity with
defined scope. Once management confirms that margin needs to be used for risks or uncertainties,
activities with both scope and budget should be added to the baseline through the appropriate change
control process. The original margin activity durations should be reduced accordingly.
Caution. Some organizations may choose to allocate budget to margin activities (i.e., “funded schedule
margin”). This is not a best practice as it effectively inflates the P/p baseline and complicates EVM
calculations by making metrics appear as though less work has been accomplished overall per the
inflated baseline.
Document the BoE for Schedule Margin
While it is essential that schedule margin activities clearly identifiable in the schedule, it is equally
important to document the rationale for the schedule margin allocation as part of the BoE in concert
with the SRA. This could include, for example, any probabilistic analysis approaches used to estimate
the necessary margin activity, including its location and duration in the schedule.
It is necessary to understand margin in the context of the IMS’s networked elements that affect it, so a
Schedule Risk Analysis-based Assessment should be performed after margin is allocated to more
completely understand the findings associated with all lower-tier assessments.
5.5.12 Perform Resource or Cost Loading
It is a best practice for the schedule to include resources and/or costs assigned to all applicable
activities at the most appropriate WBS level. “Resource loading” is defined in Appendix J of the NASA
Cost Estimation Handbook (J.1.3.4.1) as, “the process of recording resource requirements for a schedule
task/activity or a group of tasks/activities.” Cost loading refers to mapping estimated costs to the IMS.
The primary purpose of developing a resource- or cost-loaded schedule is to help ensure that NASA P/ps
can meet their commitments by using a systematic approach that integrates cost, schedule, and risk.
Resource loading or cost loading a schedule facilitates communication between the P/S or Schedule
Analyst, the Business Manager or Cost Analyst, the Technical Lead, and the PM as assumptions and risks
are documented. These practices encourage communication between Agency leadership and the PM,
affording leadership an opportunity to consider the underlying programmatic assumptions; to discuss
the analysis techniques; and ultimately, to build consensus around the conclusions (budget levels,
amount of UFE, risks involved, probability of meeting commitments, etc.) for more informed decision
making.
The following sections further describe resource loading and cost loading. These strategies should not
be viewed as conflicting approaches, but rather as two different methods of applying “resources” to the
IMS to satisfy different P/p management needs and purposes. While it is important to introduce and
distinguish the differences between resource loading and cost loading techniques, specific guidance and
information on this second approach is addressed in greater detail in Sections 6.3.2.2.1.3 and 6.3.2.2.3,
as well as within other Agency JCL instructional documentation. It should be noted that although
“resource loading” is an Agency requirement for those P/p that have a JCL requirement, cost loading is
an acceptable method.
123

Note: An additional section on budget loading follows the resource loading and cost loading sections;
however, budget loading is not a formally defined method within the Agency.
5.5.12.1 Resource Loading
Resource loading is a traditional approach involving the assignment of specific resources (i.e., workforce,
materials, equipment, etc.) to tasks within the P/p’s detailed IMS. Its basic purpose is to provide a tool
that yields insight and assistance to the PM and his team in their management of weekly and monthly of
resource allocations, and the on-going evolution of P/p budget estimates that satisfy various Agency,
program, and project budget development requirements. It helps the P/p to determine how the
availability of resources may impact the completion of tasks. This technique is sometimes referred to as
a “grassroots” estimate because the resources assigned to each task are the basis of estimate for the
cost of the task and are considered to be discrete in nature thus resulting in P/p estimates developed
coming from “the ground up”.
Resource loading provides many additional benefits that greatly enhance the P/p planning and control
process including, but not limited to:
• Ensuring accurate integration of work and budget plans (e.g., to support EVM), thereby
increasing confidence and reducing risk
• Ensuring resource availability to perform the work (e.g., labor, procurement, etc.)
• Providing greater insight into workforce adequacy and allocations
• Generating accurate inputs for the Agency Program Planning Budget Execution (PPBE) process
• Providing cash flow and budget profiles
• Providing quicker, more effective analysis for “what-if” exercises
There are however, cautions associated with resource loading which may indicate that it should not be
done, such as:
• Insufficient team resource loading skills for effective implementation and maintenance
• Scheduling tools inadequate to perform resource loading
• An undefined P/p resource pool
• Lack of clarity in contractor or subcontractor allocation of specific resources to specific portions
of the schedule (due to proprietary corporate information)
• A P/p team culture resistant to its use
Figure 5-33 provides an example of a resource-loaded schedule.
124

Figure 5-33. An example of a resource-loaded schedule.
5.5.12.1.1 Level Resources
Resource loading a schedule is the process of assigning specific people, materials, dollars, etc. to a
schedule activity or a group of activities for the purposes of estimating P/p duration, cost, feasibility, and
workforce planning. Resources can generally be put into three categories as follows:
• Workforce. The people resources assigned to do work.
• Equipment. The reusable resource items such as test or manufacturing equipment and
facilities.
• Consumables. The resources that have a specified quantity. When that quantity is used up, the
resources must be replaced (e.g., fuel, steel, cabling).
Resource loading can be done in an automated scheduling tool or in an external spreadsheet; however,
to ensure adequate cost and schedule integration, it is a recommended practice to implement resource
loading within an automated scheduling tool. Some standard practices for implementing resource
loading within an automated scheduling tool include, but are not limited to, the following:
• Prior to assigning resources to IMS tasks, it is a recommended practice that a listing of potential
resources be established within the automated schedule tool (see Figure 5-5). This resource
“library” or “pool” should contain all types of resources that will be needed for the P/p,
regardless if it is workforce, equipment, or consumables.
• It is a recommended practice that the resource pool uses a consistent resource naming
convention. This will enhance accuracy and consistency in the planning, integration, analysis,
and reporting of P/p resource data. Due to the size of P/ps and the need for flexibility to allow
multiple people within a single organization to work specific tasks, P/ps may opt to use job
125

titles/levels (e.g., Engineer, Sr. Engineer, etc.) versus individual names of personnel in the
resource pool.
Once the resource pool is complete, then task resource assignments can be made.
5.5.12.1.2 Assign Resource Rates
All resources required to perform a specific task should be selected and assigned to that task along with
quantity required. Rates for each resource are determined and applied to calculate the cost of labor,
material, or other resources assigned to each task. Resource rates are typically maintained within a
scheduling software and applied to task resources contained in the IMS. Figure 5-34 provides an
example of a “resource pool” where resource rates are maintained and applied to task resources that
are assigned in the IMS. Resource rates or per-use costs may also be maintained and applied in a
separate cost management tool that may be part of the P/p management process.
Applying resource rates to tasks is a bottom-up method of determining the time-phased budget baseline
for a P/p. Thus, it is a recommended practice to apply resource rates to tasks. This process facilitates
the implementation of EVM within the P/p and is also useful in facilitating evaluations of cost impacts
due to schedule changes. It is a recommended practice that labor quantities should be loaded in hours.
Non-labor resources may be input either as a specific dollar amount that corresponds to each
assignment of the specified resource, or as a per use amount that has an associated cost rate that is
applied within the automated tool.
Figure 5-34. An example of a resource pool captured in MS Project.
Within the resource pool contained in the automated scheduling tool, there are also specific data
elements as shown in Figure 5-35 that must be associated with each resource that are critical to
accomplishing effective resource loading. It is a recommended practice that these resource data
elements include, but are not limited to, the following (* indicates recommended minimum):
• *Resource name (specific employee names are not recommended due to dynamic work
assignment changes); add new resource names as-needed
126

• *Resource description (e.g., organization name, support contractor company name)
➢ Resource Types (e.g., workforce, material, or consumables)
• *Element of cost:
➢ *Travel (designator = Travel)
➢ *Personnel Cost (designator = CS)
➢ *Other Direct Cost (designator = ODC)
➢ *Support Contractor (designator = SUP)
➢ Equipment (designator = EQP)
➢ Contracts (designator = CON)
➢ Material (designator = MAT)
➢ Overhead and G&A (designator = OGA)
• *Center identifier (use official Center acronym)
• *Maximum number of units available Standard Unit Rate (P/p to determine)
• *Overtime Rate (P/p to determine)
• *Cost Per Use (P/p to determine)
• *Accrual method (start, prorated, end)
• *Resource Calendar (reflects active periods of resource availability - P/p to determine)
Figure 5-35. Resource pool showing associated data elements.
127

Allocation of resources may be done in various units of measure, depending on the type of resources
used. The P/S must also ensure that resources are distributed adequately across the specified task
durations. Most automated scheduling tools distribute assigned resources in a linear fashion, evenly
across the duration of a task, unless the user takes action to customize this distribution. To ensure that
a reasonable and achievable schedule plan has been developed, it is important that the P/S diligently
work through the resource loading process and establish a complete and credible basis from which to
move forward during P/p implementation. Figure 5-36 illustrates the schedule resource loading process.
Figure 5-36. The schedule resource loading process.
5.5.12.1.3 Level Resources
With respect to workforce adequacy and allocations, resource loading can provide valuable information
regarding over or under allocations in the IMS. A resource-loaded schedule provides time-phased
requirements for labor, material, and equipment. It helps to ensure cost and schedule integration and
provide the resource requirements needed to ensure that P/p resources are available when needed.
For example, this information can alert the PM where resource conflicts exist, if a task cannot be
128

completed in the time scheduled due to a resource shortage, or if adding more resources can shorten
the task duration. Most scheduling software provide the capability to identify over or under allocation
of resources. If manual processes are used to integrate resources with the schedule, similar reporting is
possible but can be much more difficult to produce. Resource leveling can help to optimize the use of
resources.
Resource leveling is the process of moving schedule tasks without violating network logic or constraints
in order to achieve a more consistent level of resources throughout the schedule duration. Analysis
through resource leveling is a process that can only be accomplished when a schedule is traditionally
resource loaded and should generally be left to the more experienced P/S. Additionally, for the process
to provide credible data, the schedule must be structured as an end-to-end logic network with all
interdependencies identified.
Resource leveling is generally accomplished through the use of a proven automated scheduling tool that
has the capability of electronically evaluating total float values, logic relationships, constraints, and the
amount of resources applied to each task or milestone in the schedule.
In carrying out this process, there are two possible methods to follow:
• Automated Resource Leveling. The scheduling tool will reschedule tasks as allowed based on
the characteristics listed above to most efficiently utilize and level the number of resources in an
effort to eliminate over allocations. Extreme caution should be used when automatically letting
the schedule tool perform resource leveling because in doing so, the tool may change or add
delays and constraints to the schedule which are not immediately detectable until a full critical
path analysis is performed. As mentioned above, only skilled qualified P/S’s should perform
these actions and even when doing so, leveling should be done in small chunks of the schedule,
if the tool allows, so the results can be seen and validated.
• Manual Resource Leveling. This method provides the most accuracy with the least amount of
error as each step of the way an “undo” can be made to correct unwanted results. To
performing manual resource leveling the user simply puts the scheduling tool in a split view with
a Gantt chart in one split and resource histogram or time phased value view in the other.
Moving from left to right, the scheduler manually accelerates or delays tasks until optimized
resource levels are achieved.
Caution. It is important to note that automated resource leveling does not factor in the varying skillsets
and availability of specific resources (people).
Examples that illustrate the how a schedule is resource leveled are provided in Figure 5-37 and Figure
5-38. See also Section 5.5.13 – Time-Phase the Schedule.
129

Figure 5-37. An example of a resource-loaded IMS with resource conflicts.
Figure 5-38. An example a resource loaded IMS with leveling to resolve resource conflicts.
130

It is very important that the resulting schedule data be reviewed by the P/p management team carefully,
and not just taken at face value. This ensures credibility for P/p implementation as well as alleviates any
other concerns that may exist relative to schedule data that are not necessarily related to float (slack),
logic, or constraints that may require adjustments to be made before baselining the schedule.
It is a recommended practice that resource leveling be performed to accurately validate whether the
scheduled P/p completion is achievable with the allotted resources (e.g., facilities, people, and budget)
based on their availability. To baseline a P/p schedule without first resource loading and conducting
leveling analysis is to assume a significant risk in achieving P/p completion within budget and on
schedule. The P/p should also take this into consideration in terms of activity duration uncertainty when
performing an SRA to analyze the achievability of the schedule.
5.5.12.2 Cost Loading
Cost loading is a cost and schedule integration approach defined in Appendix J of the NASA Cost
Estimation Handbook (J.1.6.3).75 This approach utilizes dollars as the only resource and involves the
loading of projected costs (i.e., cost estimates, not to be confused with budget) to associated tasks
within the IMS (or an Analysis Schedule, if appropriate for performing an SRA/ICSRA). Cost loading is
often viewed as less cumbersome than traditional resource loading. Recall that resource loading has
several “cautions” identified for when it should not be implemented. P/ps may also find it difficult to
properly setup and implement resource loading due to the complexity of the P/p or lack of insight to
contractor schedules that may make up a large portion of the P/p schedule. When resource loading is
deemed impractical, it is a recommended practice to implement cost loading within an automated
scheduling tool.
Per the NASA Cost Estimating Handbook, “the IMS needs to correspond to cost estimates to ensure that
enough resources can be applied to activities to complete them within the expected duration. This
should be done before the P/p schedule is baselined so that the relation between accurate cost and
schedule estimates can be verified.” Thus, cost loading is the time-phased estimate of the cost
generated by the P/p, typically through a grassroots or parametric estimate, where all the ground rules
and assumptions have been captured in a well-documented BoE.
Specifically, cost loading is accomplished by mapping cost estimates to schedule activities. The costs
should be loaded for each task according to how the cost interacts with the schedule activity. To do this,
costs are distinguished by whether they are time dependent (TD) or time independent (TI). TD costs are
a function of activity duration multiplied by the periodic value (burn-rate). If the schedule is longer than
planned, additional costs will be incurred; if the schedule is shorter than planned then less costs will be
incurred. Examples of TD costs include labor (i.e., LOE activities, “marching army”, or full-time
equivalent (FTE)/whole time equivalent (WYE)) costs, typically found in program management, systems
engineering, or safety and mission assurance activities, as well as rent, utilities, facility maintenance,
sustaining operations, or any other costs that are charged by the amount of time they are employed. TI
costs are defined as those that are fixed, irrespective of overall task duration. In other words, cost does
75 NASA Cost Estimating Handbook, Version 4.0. February 27, 2015. Appendix J.
https://www.nasa.gov/sites/default/files/files/CEH_Appj.pdf
131

not grow because of an increase in schedule duration. Examples of TI costs include procurements of
components, materials, or even a set service, in addition to tests and other expenses. Figure 5-39 shows
an Excel Workbook of the project CBS broken out by TI and TD costs.
Figure 5-39. Example of a cost loaded schedule with CBS broken out by time-dependent and time-independent costs.
Cost loading the IMS also provides a management tool that enables the P/p team to conduct an ICSRA
(or JCL) assessment. The JCL is a probabilistic assessment that is usually administered prior to key
designated P/p life cycle decision points to inform management regarding the likelihood of
programmatic success. Specifically, a JCL will assess the probability that cost will be equal to or less than
the targeted cost and schedule will be equal to or less than the targeted schedule date. Thus, it is
sufficient to use cost loading for JCL purposes. Cost loading a schedule for the purposes of performing
an ICSRA is further described in Section 6.3.2.4.
5.5.12.3 Budget Loading
Budget loading is not a formally defined “cost loading” method within the Agency. In fact, there may be
instances where someone on the P/p team may attempt to interchange the term “budget loading” with
“cost loading.” Although these terms seem similar, there is a fundamental difference between budget
and cost. The cost estimate, usually performed by the P/p, is simply the estimated costs associated with
the work packages or activities in a schedule, and implies the amount money needed (or required with a
given set of conditions/assumptions); the budget is typically derived from an external source and can be
described as the amount of money available over a set amount of time to complete the activities in the
schedule.
Normally, a budget is imposed upon the P/p (i.e., comes from the top down) and is set early on in the
P/p lifecycle when there is a lack of maturity in the requirements or understanding of the constraints.
As a result, the budget numbers are likely underestimated due to the inability to understand the
complete scope of work. In addition, the P/p usually plans to continue for a set duration according to a
set budget (i.e., ABC). The purpose of integrating the “cost” and schedule is to determine whether the
P/p can meet these commitments. Budget loading infers that budgeted dollars are assigned to the
schedule activities. Unfortunately, the budget lacks the fidelity or necessary breakdown to be able to
assign sub-budget elements to schedule activities. Consequently, the concept of budget loading a
schedule offers limited feasibility for establishing and analyzing a P/p plan.
132

Sometimes, the budget and cost estimate are consistent at the beginning of the project, but an
underperforming contractor on a cost-plus-fixed-fee (CPFF) contract causes the costs to quickly exceed
the budget. In these instances, spreading the budget across activities, thereby budget loading the
schedule, underestimates the potential actual costs. A budget may also have political implications and
carry embedded risk. In addition, phasing constraints and funding profiles can impact a P/p’s budget,
which can then become a reduction from the grassroots estimates and/or modeled cost estimate. Given
these factors, the budget may or may not be aligned with the P/p’s cost estimate. An ICSRA performed
on a budget-loaded schedule carries embedded risk, since the budget is generally assumed to be a
reduction of the grassroots or modeled cost estimate. Because the budget does not reflect the
expected costs of the project (e.g., historical resource costs/cost trends, risks and uncertainties that can
cause schedule delays resulting in increased costs, etc.), budget loading may underestimate projected
costs and ultimately not provide a credible confidence level. Thus, budget loading should be avoided.
Document the BoE for Resource or Cost Loading
It is important to document in the BoE any assumptions related to the resource or cost loading of the
schedule, which may include rationale for the level at which costs or resources are loaded. It is also
necessary to reference (and include where possible) any applicable source documentation (e.g., WBS
Dictionary, PPBE, independent cost estimate(s), resource rates, etc.) as part of the BoE.
Marrying the financial and schedule domains together is perhaps the most delicate schedule
development procedure. As such, its applicable assessment activity, the Resource Integration
Assessment procedure, proves invaluable in affirming that this these domains are at least mechanically
aligned.
5.5.13 Time-phase the Schedule to Align with the Availability of Funding
After completion of the above steps, it is a best practice for the schedule to be time-phased to align
with the availability of funding to provide the earliest possible finish date. The time-phasing of tasks
included in the IMS in accordance with available funding is critical to successful development of an
integrated baseline, or when applicable, the development of a formal PMB and implementation of EVM.
Figure 5-40 illustrates the relationship between P/p funding, the P/p budget plan, and the P/p schedule.
133

Figure 5-40. The relationship between P/p funding, the P/p budget plan, and the P/p schedule.
There are many situations related to the P/p budget and funding that may dictate when and how quickly
activities can be performed, which directly contribute to how the schedule is time-phased. Still other
situations may cause the P/p to intentionally re-phase the schedule such that those conditions can be
met. Typical situations are as follows:
• Budget Availability. Often within NASA, the annual budgeting process and the most efficient
P/p schedule do not match. The annual budgeting process tends to be a flat line, whereas the
most efficient P/p schedules will follow a ramp-up, peaking before CDR, then ramp-down to a
lower level for I&T and launch vehicle integration. Smoothing the peak funding can be
accomplished by using the SNET constraint or lags to move activities into a subsequent fiscal
year. When perfect leveling cannot be achieved, other techniques may also be utilized such as
planning for budget carryover from underutilized years to over-utilized years. For time periods
that underutilize available budget, schedule compression techniques are an option (See Section
7.3.4.5).
• Continuing Resolution. Continuing Resolution (CR) occurs when Congress is unable to pass the
budget in time for the fiscal year start. The CR process will hold current spend levels flat until
the new FY budget can be passed. CRs have become common recently and can last for several
months or more. It may be worthwhile to consider planning the schedule such that the required
budget will remain flat from October through December.
• Facility Availability. Major facilities such as wind tunnels, vibro-acoustic chambers, and vacuum
chambers are in high demand and may not be available at the time the P/p needs them. In such
cases, using a SNET may be a valid approach.
134

• Human Resources. Staffing and specialty skills may be limited or unavailable when the planned
schedule activities require them. If the schedule is resource loaded, scheduling tools support
resource-leveling which will stretch or move activities to bring the needed level into compliance
with available resources. If the schedule is not resource-loaded, the SNET constraint and
manual stretching the duration can be used to match the activities to available personnel.
Document the BoE for Time Phasing the Schedule to Align with the Availability of Funding
While resource or cost loading the schedule can help to ensure that the cost estimate is aligned with
scheduled activities, it is also important to make sure that the P/p budget, and the availability of that
funding, is adequate to support the time phasing of the activities. It is important to document any
assumptions associated with the available funding as part of the schedule BoE, including any special
circumstances related to how much budget is available and when. Further, like the Schedule Risk
Analysis-based Assessment before it in Section 5.5.10, the Integrated Cost and Schedule Analysis-based
Assessment procedure should be executed after this schedule development step to shed new light on
assessment findings and augment the BoE.
5.5.14 Map Risks to the Schedule
It is a best practice for discrete risks to be quantified and mapped to appropriate activities within
schedule. The Risk Management function needs to effectively collaborate with other PP&C functions to
develop products and strategies that support the development of an integrated and executable P/p
plan, and maintain risk-intensive assessments, analyses, tracking, and reporting throughout the P/p life
cycle. The P/S should strive to integrate risk information into the schedule. Risks should always be
treated by the P/S as elements inseparable from the IMS and worthy of close examination; their
parameters, including placement in the IMS, should be assessed in similar manner to all other schedule
elements. In the ideal case, a risk owner, in coordination with the P/S and Cost Analyst or Business
Manager, should provide justified schedule likelihood and impact estimates in addition to the risk matrix
scores.
Often the P/p will have identified risk mitigation plans for the actionable risks. Risk Mitigation is an
action or series of actions put into place by P/p management to reduce the likelihood of risk occurrence
or the impact from the risk event. Detailed risk mitigation plans include detailed information as to the
mitigation action(s), timeframe for the mitigation, resources required for mitigation, expected results,
alternatives, and costs of mitigation effort. When such risk mitigation burn-down plans are available,
each mitigation activity should be mapped to the schedule at the appropriate location along with a
justification for the expected risk score and quantification after the mitigation activity is complete. The
level of post-mitigation risk is known as residual risk. Residual risk represents the likelihood of the risk
event and impact of the risk event after mitigation activities are enacted.
Note: An “accepted” risk’s schedule consequences should augment the baseline IMS; likewise, the
accepted risk’s cost consequences should be incorporated into P/p cost estimates and budget plans.
Document the BoE for the Schedule Risks
The IMS cannot be fully understood without examining the DNA of schedule risks. Each schedule risk’s
parameter set and assumptions, including location within the IMS, should be documented within the
BoE. This information may be newly uncovered via the Risk ID and Mapping Check, as defined in Section
135

6.2.2.1.3, and the Basis Check, as defined in Section 6.2.2.2.2, all of which should be performed on a
continuous basis. It is also possible that each risk’s owner may have included basis rationale within the
RMS. Regardless, all risk basis rationale and supporting data should be collected within the BoE to
support cohesive schedule assessment and analysis.
5.6 Develop the Schedule Outputs
It is a best practice for the IMS to be the foundation for all schedule-related information. The Schedule
Database must be developed such that it can output the following four key types of Schedule Outputs:
• Integrated Master Schedule. An IMS is the complete, time-phased, logically-linked network of
all P/p effort that is required to ensure that all objectives are met within approved
commitments. The use of the word “integrated” implies the incorporation of all activities, even
contractor and subcontractor efforts, necessary to complete the P/p. The IMS is utilized as the
P/p management tool that integrates the planned work, the resources necessary to accomplish
that work, and the associated budget.76 The IMS is the backbone for managing the P/p
successfully, which includes establishing the PMB, measuring and forecasting performance,
controlling the baseline, and communicating the overall progress against the plan.
• Summary Schedule. A Summary Schedule is a high-level roll-up of the IMS and is used for
management reporting. It is a direct derivative of the IMS and should mimic the critical paths
within the IMS.
• Analysis Schedule. An Analysis Schedule, if required, can be generated from the Schedule
Database when needed for schedule risk analysis or integrated cost and schedule risk analysis
(SRA/ICSRA). An Analysis Schedule should be directly traceable to the IMS, replicate the critical
paths, and emulate the IMS; however, it may have additional tasks to model the potential
impact of discrete risks.
• Schedule Performance Measures. Schedule Performance Measures are produced by
incorporating current performance data with the planned performance in the IMS. Schedule
Performance Reports are typically created monthly and may capture schedule status, progress,
or forecasts. All are clearly identified and archived following the version control requirements
within the configuration control process.
• Schedule BoE. The Schedule BoE is the documentation of the ground rules, assumptions, and
drivers used in developing the cost and schedule estimate, including applicable model inputs,
rationale or justification for analogies, and details supporting cost and schedule estimates.”77
The Schedule BoE dossier acts as a comprehensive, structured collection of technical and
programmatic information necessary to fully develop, understand, assess, analyze, and
theoretically reproduce the IMS, while also playing a supplementary role in schedule
76 GAO-16-89G. GAO Schedule Assessment Guide. December 2015. Page 5. https://www.gao.gov/assets/680/674404.pdf
77 NPR 7120.5E. NASA Space Flight Program and Project Management Requirements. Effective Date: August 14, 2012.
Expiration Date: August 14, 2020. Appendix A.
https://nodis3.gsfc.nasa.gov/npg_img/N_PR_7120_005E_/N_PR_7120_005E_.pdf
136

maintenance and control. (Because the BoE is described in Section 5.4, it is not repeated in the
subsections that follow.)
5.6.1 Integrated Master Schedule (IMS)
The IMS is the primary output from the Schedule Database. The purpose of an IMS is to provide a time-
phased plan, or “point estimate”, for performing the P/p’s approved total scope of work and achieving
the P/p’s goals and objectives within a determined timeframe and with acceptable risk. Whether
developed for a Program or project, the IMS can be utilized as the P/p management tool that integrates
the planned work (including both government and contractor work), the resources necessary to
accomplish that work, and the associated budget, thereby facilitating other PP&C functions and
supporting processes that help with maintaining the P/p baseline.
A properly prepared IMS provides a roadmap from which the P/p team can execute all authorized work
and determine where deviations from the baseline plan have created a need for informal changes or
formal corrective actions. Prior to establishing the baseline, the schedule is referred to as the
preliminary schedule or preliminary IMS; once baselined, it is the “schedule baseline” or “baseline IMS”.
The IMS is baselined, usually through an Integrated Baseline Review (IBR), and progress is measured
from this baseline throughout the P/p life cycle. The baseline IMS provides the approved, time-phased
P/p schedule plan of the work to be performed that serves as the basis for performance measurement
during P/p implementation. As performance variances exceed prescribed thresholds, or new content is
added, corrective actions may be taken, or the baseline may be changed through the P/p’s CM/DM
process. The processes for establishing and controlling the schedule baseline are discussed in Chapter 7.
It is a best practice for the schedule to reflect vertical traceability in that any and all supporting
schedules contain consistent information and can be traced to the IMS. The IMS is traceable to the
WBS, the SOW, Contractor Performance Report (CPR), and the EVMS. P/p risks and risk mitigations
should be traceable to the IMS, as applicable. Vertical traceability allows for total schedule integrity and
enables different teams to work to the same schedule expectations. Schedules are typically categorized
according to three levels of detail:
• Summary Level. A Summary Schedule is one-page report that represents a high-level roll up of
the IMS and may be generated for a Program, for individual projects within a Program, or for
sub-projects of a project. It contains key summary activities and milestones depicted in a Gantt
chart, typically at the second-level WBS (e.g., subsystem level); although, the level of the roll-up
depends on the level of detail that will offer the PM or other stakeholders the appropriate level
of insight. The Summary Schedule should clearly identify the critical path at the summary level
and also show any areas of the schedule that contain margin. A Summary Schedule is often
referred to as a “Master Schedule” when it reflects a summary IMS for the complete P/p;
however, a Summary Schedule is not an IMS, and should not be used as a substitution for an IMS
when an IMS is required.
• Intermediate Level. The intermediate schedules are at a lower resolution of work to be
performed than what is depicted in the Summary Schedule, but at a higher level than the
Detailed Schedule(s). Early in the P/p life cycle, intermediate schedules may represent early
stages of the rolling wave approach (i.e., top-down). Later in the life cycle, they may be slightly
137

summarized versions of more detailed schedules (i.e., bottoms-up). Intermediate schedules are
logic network schedules (i.e., CPM schedules) and reflect relationships among key events, start,
finish, and baseline dates for activities, as well as total float for each activity. Intermediate
schedules should be organized according to the WBS and support the key dates in the IMS.
Intermediate schedules should also clearly identify the critical path.
• Detailed Schedules. The detailed schedules are the lowest-level P/p element schedules
available that identify discrete work packages for a specific schedule element, such as a specific
WBS. Detailed schedules illustrate horizontal dependencies and are used to track and control
work progress at the lowest level. Detailed schedules are logic network schedules (e.g., CPM),
and should depict activity logic, start, finish, and baseline dates for detailed activities, as well as
the total float for each detailed activity. Detailed schedules should also reflect any other activity
attributes, such as leads/lags, uncertainty/risks, etc. It is critical that the activities in a detailed
schedule be defined at a low enough level to allow for finish-to-start interdependency
relationships where feasible, accurate progress measurement, issue identification, and
traceability to higher level milestones. In addition, detailed schedules should clearly identify the
critical path(s). If the detailed schedules are resource or cost loaded for the purposes of an
ICSRA/JCL, they may also require traceability to the CBS.
Estimates for all work activities establish a logical hierarchy from the detailed activity level to
intermediate to P/p summary levels, and contain baseline, actual, and forecast dates for each activity.
Thus, the IMS is a hierarchical, tiered network capable of rolling up to high-level summary
representations of activities, as well as breaking down to the lowest level of task details showing
dependencies, resources, durations, and constraints. Using the assigned coding structure, the
scheduling tool is able to filter and summarize schedule data to provide reports at each of these levels.
An activity owner should be able to trace detailed activities to higher-level summary activities within
intermediate- and summary-level schedules. In much the same way, the PM should be able to trace
summary activities down their more detailed components or work packages. As shown in Figure 5-41,
sub-project schedules can be separately maintained by the owning organizations, and as required, be
provided to the P/p on a regular basis with appropriate status/performance data to serve as an update
to the P/p IMS. Even though the sub-project activities may be rolled into a higher-level summary task or
milestone, Technical Leads (e.g., CAMs, WBS Element Owners, etc.) should be able to identify when and
how their activities affect the overall P/p schedule. Any descriptive narrative associated with the
traceability of different levels of the schedule to one another should be captured as part of the BoE.
138

Figure 5-41. All levels of the P/p schedule should be vertically traceable to each other, reflecting consistent schedule data.
The level of insight and analysis that can be achieved from the schedule is heavily dependent on the
level of detail contained in the IMS, which is important to accomplishing the three continuous schedule
management processes: Schedule Assessment and Analysis, Schedule Maintenance and Control, and
Schedule Documentation and Communication. For instance, detailed critical path identification and
analysis, as well as detailed insight into P/p issues cannot be done with only summary-level schedule
content. Instead, the detail in the IMS is sufficient to identify the longest path of activities through the
entire P/p.78 For any reporting requirements that specify an “IMS”, the complete IMS in its native file
format should be delivered (e.g., to the SRB during P/p Life Cycle Reviews, or as part of the NASA
Corrective Action Plan Schedule Repository Initiative).
While each of the three levels of schedule detail likely exist for every element of the P/p (e.g.,
subsystem, instrument, sub-project), oftentimes, what goes into the P/p IMS is a mix of all three levels
of the supporting work elements, depending on the relationships of the individual Element Owners to
the P/p itself. For instance, a P/p IMS may have elements that are at a summary level, such as work
78 GAO-16-89G. GAO Schedule Assessment Guide. December 2015. Page 11. https://www.gao.gov/assets/680/674404.pdf
139

performed by international partners or parts procured from vendors, where only summary tasks and
delivery milestones are available. For contracted portions of the P/p IMS, the schedule may contain
work defined at an intermediate level. Elements of work that are performed in-house may be carried at
a detailed level to facilitate more rigorous Schedule Control.
A Program IMS may consist of one or more project schedules. Within NASA, Research and Technology
Programs (NPR 7120.8) are those which are strictly comprised of R&T projects. Space Flight Programs
(NPR 7120.5) are categorized according to the following four groups:
• Tightly Coupled Programs contain multiple projects that have a high degree of organizational,
programmatic, and technical commonality. This type of Program requires a much higher degree
of integration between the projects potentially resulting in numerous inter-project
interdependencies in the Program IMS.
• Loosely Coupled Programs contain projects that have organizational commonality, but little
programmatic or technical commonality. These projects will typically have minimal or no inter-
project interdependencies in the Program IMS.
• Uncoupled Programs contain projects that are implemented under a broad scientific theme
and/or a common implementation concept, but each project will be independent of other
projects in the Program. These projects will have minimal or no inter-project interdependencies
in the Program IMS.
The level of detail contained in the Program IMS will generally depend on two key factors:
• The level of management insight desired by the Program
• The magnitude of Program scope and the amount of project data to be maintained and analyzed
at the Program level
Note: Potential compatibility issues between Program- and project-level schedule management tools
should be worked out during Planning and should not be a constraint on a Program’s ability to perform
adequate Schedule Management.
Much in the same way a Program schedule may be composed of multiple project schedules, it is not
unusual for a Single-project Program or project IMS to be an integration of several sub-projects.
• Single-Project Programs have only one project that makes up the Program. For this type, the
Program IMS will most likely not have interdependencies to other projects. These Programs
tend to have long development and/or operational lifetimes, represent a large investment of
Agency resources, and have contributions from multiple organizations/agencies. These
Programs frequently combine Program and project management approaches, which they
document through tailoring.
• Projects often have interfaces with other projects, agencies, and/or international partners. In
other cases, a space flight project may have a prime contractor developing the primary science
instrument or spacecraft system. An R&T portfolio project may be made up of one or more
groups of R&T investigations that address the goals and objectives of the R&T portfolio
140

project.79 The sub-projects may be separately managed and maintained by other organizations
or by external contractors. Whether primarily “in-house” or not, the project IMS will most likely
have interdependencies to other organizations.
It is important to note that different organizations may use the term "integrated master schedule" as it
pertains to them. For example, a project IMS may represent a detailed schedule that gets summarized
at an intermediate or even summary level for inclusion in the Program IMS. Similarly, a sub-project
work-package level schedule may be the sub-project’s IMS; however, the same schedule would serve as
a detailed schedule for the “parent” project. When discussing the work of a prime contractor, the term
“IMS” may be used to refer solely to the prime contractor’s schedule. In actual practice, the
government IMS usually incorporates intermediate- or summary-level elements of the contractor's IMS,
whereas the contractor's IMS, at its lowest level, includes the individual activities necessary to complete
each work package. Should the government require more insight into the contractor schedule, it is
possible that a request, by way of contract language, would be made for intermediate schedules or
detailed schedules from the contractor for either specific elements of the contractors work or the entire
contractor “IMS”. In general, there are five techniques for characterizing the P/p IMS as shown in Figure
5-42.
Figure 5-42. A summary of the five different techniques for developing the IMS.
79 NPR 7120.5E. NASA Space Flight Program and Project Management Requirements. Effective Date: August 14, 2012.
Expiration Date: August 14, 2020. Page 11. https://nodis3.gsfc.nasa.gov/npg_img/N_PR_7120_005E_/N_PR_7120_005E_.pdf
141

The five IMS development techniques acknowledge the differences among NASA’s P/p types, acquisition
strategies, external partnering agreements, and other factors. Similarly, the IMS development
techniques have various advantages and disadvantages which are summarized in Figure 5-43.
Figure 5-43. A summary of the advantages and disadvantages of each IMS development technique.
While there are no mandatory rules for matching IMS development with P/p types, Figure 5-44 offers
some general guidance on which IMS technique is suitable for specific P/p types. The five techniques
are further described below.
Figure 5-44. Suggested mapping of each IMS development technique to P/p types.
142

Single Consolidated P/p IMS
With the Single Consolidated P/p IMS, all of the P/p work scope is incorporated into a single IMS
schedule file encompassing NASA in-house, contractor, and partner efforts. If interrelationships exist
between any of the provider schedules, then appropriate logic relationships should be included to
accurately model those interdependencies. Where these interdependencies exist, it is appropriate that
the P/p manage agreements (e.g., MOAs, MOUs, etc.) between the elements.
This technique does not necessarily prescribe that the native IMS files from the providing organizations
are directly integrated into the P/p IMS. For example, in some cases the P/S creates a summary or
intermediate level version of a provider’s schedule that is incorporated into the P/p IMS. However, it is
a recommended practice that the entire scope of work be broken into schedule tasks and milestones at
a consistent level of detail to allow discrete progress measurement and visibility into the overall design,
fabrication, integration, assembly, test, and delivery phases of each end item deliverable. Additionally,
all schedule tasks/milestones should be integrated with the appropriate sequence relationships to
provide a total end-to-end logic network leading to each end-item delivery.
The Single Consolidated P/p IMS should contain all contract and controlled milestones, key
subcontractor milestones, end item delivery dates, key data delivery dates, and key Government
Furnished Property (GFP) need dates. For Programs, all tasks and milestones reflecting effort to be
implemented specifically at the Program level must also be included, as well as all Program-level control
milestones that have been established. The IMS should also contain the appropriate field codes
necessary to provide sort, select, and summarization capabilities for, but not limited to, WBS element,
project phase, and level-of-effort tasks. In-house and contractor schedules supporting the overall IMS
should capture the necessary P/p information according to Agency or P/p required field codes.
Once the integration of all in-house and provider schedules into a Single Consolidated P/p IMS is
complete, the P/S should validate the IMS through Schedule Assessment checks and reviews by the
input stakeholders. Since the IMS serves as the basis for identification of critical paths and driving paths,
as well as work-off and performance trending, schedule risk assessments, and “what-if” analysis, this
strategy provides the overall capability for integrated insight and oversight of all project work.
Caution. Most scheduling software supports the integration of multiple or external schedules, assuming
the schedules are built in the same tool. If using different tools, the schedule data may need to be
exported into a data file and then imported into the consolidated IMS. For on-going schedule
integration, capturing activity and milestone information may require reconciling status dates between
in-house and contractor schedules, as well as a careful consideration of calendars and cost or resource
loading techniques applied to each schedule.
Master P/p IMS (with sub-projects)
The Master P/p IMS technique is similar to the single consolidated P/p IMS technique described above,
except that in this case, a Master IMS file is created that provides the schedule backbone for crosslinking
the interdependencies among the supporting provider organizations’ individual IMS sub-project
schedule files.
143

P/p Control Milestone Integration IMS
With the P/p Control Milestone Integration IMS technique, in-house, contractor, and other partner-
provided IMS files are retained and monitored in their native formats. Horizontal schedule integration is
maintained through the identification and tracking of significant receivable and deliverable milestones
between the individual schedules.
Note: One of the challenges with the P/p Control Milestone Integration IMS technique is that external
stakeholders may feel that a true end-to-end IMS does not exist for the P/p. Using milestone sets to
reflect the major events in accomplishing the complete P/p effort is seldom an effective practice for the
P/p’s insight/oversight purposes, as it is not conducive to sound schedule analysis or meaningful insight
into overall P/p performance. Underlying interdependencies are much more difficult to reflect
accurately when using this technique. This difficulty is due to the technique in which the P/S must
account for the effort being carried out in between the milestones. In order for the P/p IMS to keep the
proper time-phasing for the numerous provider milestones the P/S must either incorporate appropriate
schedule lag values between each milestone (not a best practice) or assign date constraints to each
milestone included in the schedule (also not a best practice). A way to address this concern is for the
P/S to periodically create either a Single Consolidated IMS file or Master P/p IMS file with sub-projects
and directly link the predecessor and successor relationships to validate the logic among P/p elements.
A recommendation is to perform this cross-check schedule integration in advance of major LCRs.
Summary P/p Master Logic Network IMS
With the Summary P/p Master Logic Network IMS technique, the P/S, in coordination with the P/p team,
develops and maintains a summarized logic network derived from the detailed schedules from the
provider organizations. When prime contractors are involved, the government IMS usually incorporates
summary-level elements of the contractor's IMS, whereas the contractor's IMS includes the detail-level
activities necessary to complete each work package. In these instances, although all contractor work-
package level detail is not contained in the NASA P/p IMS, the term “integrated” implies the schedule’s
incorporation of representative activities and milestones, those of the provider organization’s major
efforts, which reflect the overall network logic necessary to complete the P/p and replicate critical paths
and driving paths.
The P/S ensures that the Summary P/p Master Logic Network IMS traces to, and reconciles with, the
provider IMSs. It is important to keep the level of summarization consistent with the desired level of
insight, as influenced by cost, risk, and criticality (both schedule and technical). Interdependency
relationships for all summary tasks and milestones should be established and maintained. Inter-
organization logic relationships should be identified.
Caution. This approach may prove to be of limited use when performing critical path identification and
analysis. Summary-level schedule data will not typically identify many of the detailed integration points
needed for accurate task sequencing. The resulting impact is that accurate critical path logic flows
cannot be identified. This potentially leads to erroneous summary-level critical path information which
is not accurate or consistent with the detailed critical path information. It must be acknowledged and
understood by the P/p team that when using summary-level IMS data, the level of insight, control, and
analysis will also have to be raised to a higher level. This means that the P/p team will have to depend
144

more heavily on the detailed schedule insight and analysis provided by the provider organizations, which
is not usually adequate for achieving integrated Program insight.
Prime Contractor-based P/p IMS
With the Prime Contractor-based P/p IMS technique, the uses the prime contractor’s IMS at the P/p
IMS. This technique is used when the P/p’s work essentially consists of overseeing a single prime
contractor whose effort comprises the majority of the P/p work scope.
Caution. In the case of contracted efforts, the P/p needs to ensure that the contractor is required to
deliver a schedule that reflects the level of detail necessary for PM oversight. It is recommended that
Prime Contractor-based IMSs be composed of all supporting P/p schedule information at least at an
intermediate level of detail for the contracted effort. The NASA P/p should also consider maintaining an
“add-on” schedule reflecting effort that falls directly under the responsibility of the NASA P/p Office.
The latter portion will allow for adequate P/p Office oversight and control of the work for which they are
directly responsible.
5.6.2 Summary Schedule
A Summary Schedule is a high-level roll-up of the IMS and is used for management reporting. It is a
direct derivative of the IMS and should mimic the critical paths calculated in the IMS. It is important to
note that tools other than the scheduling software may be needed to create a Summary Schedule that is
useful to P/p Management; however, the IMS should be the source of the information used to create
the Summary Schedule. Typically, the Summary Schedule is rolled-up to the second-level WBS (e.g.
subsystem level). However, it is important that the level of roll-up be determined by the critical paths
because that is usually the detail that P/p management needs to review. For example, if it is necessary
to show how a critical path flows through a third-level WBS item, that particular subsystem needs to be
further decomposed. Figure 5-45 is an example from a NASA project. It is rolled-up to the subsystem
level and shows key milestones, status date (“time now”), critical paths, available margin, and other
information deemed important by P/p management. Additional examples of Summary Schedules are
provided in Chapter 8.
145

|     | Calendar  | 2010 |     |     | 2011 |     |     |     | 2012 |     | 2013 |     |
| --- | --------- | ---- | --- | --- | ---- | --- | --- | --- | ---- | --- | ---- | --- |
|     | Year      | 2 3  | 4   | 1   | 2    | 3   | 4   | 1   | 2 3  | 4 1 | 2 3  | 4   |
MPArVoEjNec Mt iMlesilteosnteosnes
|     |                     | Phase          |                      |     | Phase C 21.5 Mos       |           |     |                 |          | Phase D 16 Mos   |               |     |
| --- | ------------------- | -------------- | -------------------- | --- | ---------------------- | --------- | --- | --------------- | -------- | ---------------- | ------------- | --- |
|     |                     | B 7/12         |                      |     |                        |           |     |                 | 7/10 SIR |                  | 11/18  Launch |     |
|     | Confirmation RvP DR |                |                      |     |                        | 7/15  CDR |     |                 |          | Ship to KSC 8/6  |               |     |
|     |                     |                | 11/1  C/D ATP        |     |                        |           |     | ATLO Start 8/13 |          |                  |               |     |
|     |                     | 6/215 0 / C8 o | m p l e te  S/S PDRs |     | Final ICDs/Fault Trees |           |     |                 | F i n    | a l  LV-S/C Dyn  |               |     |
Systems Eng.WBS –
|        |     | R e f e  | re n c e             |     |            |               |     |                        | M o                       | d e l |     |     |
| ------ | --- | -------- | -------------------- | --- | ---------- | ------------- | --- | ---------------------- | ------------------------- | ----- | --- | --- |
| 6.2.02 |     | Mission  |                      |     |            | Database      |     | Sun SensorStar Tracker |                           |       |     |     |
|        |     | Avail    | Initial SW Algorithm |     | Alg Update | ParametersIMU |     |                        | Reaction Wheel Assy Avail |       |     |     |
GN&C WBS –6.2.04
|     |     |     |     | Therm. Memos |     | RS Thermal Blank |     | P&F Thermal Blank |     | MLI Build 1MLI Build 2 |     |     |
| --- | --- | --- | --- | ------------ | --- | ---------------- | --- | ----------------- | --- | ---------------------- | --- | --- |
Thermal WBS –6.2.05
|     |     |     |     |     |     |     | Static Test  | EDU Gimbal FL 2-Axis Gimbal |     |     |     |     |
| --- | --- | --- | --- | --- | --- | --- | ------------ | --------------------------- | --- | --- | --- | --- |
Wing #1
|                        |     |                     |     |           |     | Test PAF     |               | Lifetest Compl  |                                  | Wing #2 |     |     |
| ---------------------- | --- | ------------------- | --- | --------- | --- | ------------ | ------------- | --------------- | -------------------------------- | ------- | --- | --- |
| Mechanical WBS –6.2.06 |     |                     |     |           |     |              |               |                 |                                  |         |     |     |
|                        |     |                     |     |           |     | Fuel  Ta n k |  Structure to |   P r o p       | I n te g . Str./Prop. Module to  |         |     |     |
|                        |     | Tank Forgings Avail |     | PMD Compl |     | A va i       | l             |                 | A T L O                          |         |     |     |
| Propulsion WBS –6.2.07 |     |                     |     |           |     |              |               | P r o o f  Test |                                  |         |     |     |
PAPU Avail
|     |     |     |     |     |     |     |     | PDDU Avail |     | Flt Batteries Avail |     |     |
| --- | --- | --- | --- | --- | --- | --- | --- | ---------- | --- | ------------------- | --- | --- |
Power WBS –6.2.08
|                  |     | DTCI-U IRAD Card Avail |     |     |                        | Rad 750 FL  |     |                  |     |     |     |     |
| ---------------- | --- | ---------------------- | --- | --- | ---------------------- | ----------- | --- | ---------------- | --- | --- | --- | --- |
|                  |     |                        |     |     | C&DH EDU #1 AvaUinlits |             |     | C&DH Boxes Avail |     |     |     |     |
| C&DH WBS –6.2.09 |     |                        |     |     |                        |             |     | #1#2             |     |     |     |     |
Telcon Panel Build ComplPanel FunctTest Compl
| Telecom WBS –6.2.10 |                           |     |     | HGA PDR |           | HGA CDR   |                |             | HGA Avail         | SDST Avail |     |     |
| ------------------- | ------------------------- | --- | --- | ------- | --------- | --------- | -------------- | ----------- | ----------------- | ---------- | --- | --- |
|                     |                           |     |     |         |           | S A Qual  | Gimbal Harness |             | SA/MAG Harness #2 |            |     |     |
| Harness WBS –6.2.11 | Margin to Ship = 104 days |     |     |         | STL Harne | ss        |                | Bus Harness |                   |            |     |     |
Margin % to Ship = 18.2%
Margin to Launch = 122 days
|     |     |     |     |     |     |     | S/W 3.0  | S/W 4.0  |     |     |     |     |
| --- | --- | --- | --- | --- | --- | --- | -------- | -------- | --- | --- | --- | --- |
Software WBS –6.2.1M2argin % to Launch = 19%S/W 1.0 (OS) S/W 2.0 (I/O) (Telecom/Fault)(Fault & P/L) S/W 5.0 (P/L) S/W 6.0 (Flt)
|     |     |     |     | GDS Bld 1.0 |     |     |     |     |     |     | Start |     |
| --- | --- | --- | --- | ----------- | --- | --- | --- | --- | --- | --- | ----- | --- |
Mission Ops/GDS WBS – MOS PDR Bld 2.0 MOS CDR Bld 3.0 GDS Bld 4.0 ORTs GDS Bld 5.0
| 7.2/9.2       | Legend |     |     |     |                        |     |                 |     |     |     |     |     |
| ------------- | ------ | --- | --- | --- | ---------------------- | --- | --------------- | --- | --- | --- | --- | --- |
| Testbed (STL) |        |     |     |     | Start  STL Integration |     | STL Operational |     |     |     |     |     |
= Schedule Margin
| WBS –10.2.03 | = Primary Critical Path |     |     |     |     |     |     |     |     |     |     |     |
| ------------ | ----------------------- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
ATLO WBS –10.2.01 = Secondary Critical Path Flt Payloads Avail Sine Vibe Test Ship LV Mate
|     | = Tertiary Critical Path |     |     |     |     |     |     |     |     | TVac | Launch 11/18 |     |
| --- | ------------------------ | --- | --- | --- | --- | --- | --- | --- | --- | ---- | ------------ | --- |
Time Now
| IMS Rev.4: 04/24/11 |     |     |     |     |     |     |     |     |     |     |     |     |
| ------------------- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
Figure 5-45.  A typical Summary Schedule “output” from the Schedule Database is shown here. It includes the primary,
secondary and tertiary critical paths.
While a Summary Schedule is often used for high-level schedule reporting, a Summary Schedule should
never be used as a substitute for the P/p IMS, when an IMS is explicitly required.  This is in direct
contravention of the definition of an IMS.
5.6.3  Analysis Schedule
For complex projects, it is recommended that an Analysis Schedule be developed to perform Schedule
Risk Analysis (SRA) and/or Integrated Cost and Schedule Risk Analysis (ICSRA), as needed.  An Analysis
Schedule, while similar to the Summary Schedule in that it is a high-level overview of the IMS, should not
be developed using a standard, across-the-board roll-up approach.  One major difference is that the
Analysis Schedule roll-up must be done such that WBS items that are impacted by risks or uncertainties
must be included.  Thus, the level of roll-up can vary across the schedule.  For example, it may be
appropriate to roll-up Command and Data Handling (C&DH) to the subsystem level because there are no
significant risks affecting the C&DH.  Whereas, the Power and Propulsion for the same schedule may
need be detailed down to the component level to capture a risk on a new technology for valves on a
reaction control jet.  A second difference is the need for Analysis Schedules to capture additional
activities for cost modeling, such as hammocks, or additional “placeholder activities” along with
appropriate linkages provided for modeling potential interference at specialty work stations or test
facilities.
•
Placeholder Activity.  Often placeholder activities or links need to be added to the Analysis
Schedule network (or IMS if being used for the SRA/ICSRA) to cause it to behave as it should
146

under the influence of risk and uncertainty. For example, assume the natural design of the
schedule under normal circumstances will not allow two units to enter a test facility at the same
time. Under risk and uncertainty, it may be possible for two units to arrive at the same time,
thus necessitating the need for an extra link in the network. Another example is the addition of
activities to resolve conflicts as risk and uncertainty move the activities around in the network,
such as a swap-out of a flight unit for a development unit should a flight unit be delayed due to
risk.
An Analysis Schedule should reflect the appropriate level of fidelity, such that it is directly traceable to
the IMS, replicates the critical paths, and emulate the IMS under the influence of risks and uncertainties.
Greater detail on how to develop an Analysis Schedule is discussed in Section 6.3.2.3.1.
5.6.4 Schedule Performance Measures/Reports
Schedule Performance Measures communicate vital information about the status or performance of a
system, process, or activity for contractor and in-house efforts. Regular progress updates for work
performed in-house by NASA organizations, as well as for contracted or external partner work, feeds the
Schedule Database all data needed to output the necessary Schedule Performance Measures.
While the P/p may have specific performance measurements, as documented in the SMP,
Typical performance data utilized by most P/ps can be generated Schedule Analysis (Section 6.3.2.5) and
Schedule Control (Section 7.3.3). This information feeds into the Schedule Communication and
Documentation sub-function to support the reporting process.
Schedule Performance Reports are typically created monthly and may capture schedule status, progress,
or forecasts. All are clearly identified and archived following the version control requirements within
the configuration control process. Report types are described in Section 8.3.2.4 and include, but are not
limited to:
• IMS/Summary Schedule. Used to facilitate additional analysis that will aid in both routine
Schedule Management, as well as P/p Management decision making through various reporting
forums, such as Center Management Councils (CMCs) or through Monthly Status Reports
(MSRs).
• Critical Path (Deterministic and Stochastic). Used to show all tasks and milestones that make
up the critical path(s) (primary, secondary, tertiary, etc.) with the associated amounts of total
float.
• Critical Path Length Index (CPLI). Used to describe the efficiency required to complete a
schedule milestone on time.
• Margin Consumption and Total Float Status/Float (Slack) Erosion. Used to feed float erosion
tracking tables by activity.
• Resource Leveling. Used to show whether the scheduled P/p completion is achievable with the
allotted resources (e.g., facilities, people, and budget) based on their availability.
147

• Activity/Milestone Variances and Schedule Variance (SV). Used to show status or track actual
performance against planned progress of activities/milestones and to feed EVM calculations
over time.
• Activity/Milestone Performance Trends. Used to communicate progress against baseline as
well as changes in the schedule progress month-to-month.
• Baseline Execution Index (BEI), Hit or Miss Index (HMI), and Current Execution Index (CEI).
Used to understand the difference between cumulative performance or performance within a
certain window and planned performance.
• Schedule Performance Index (SPI), Time-based SPI (SPI), and Earned Schedule. Used to
measure schedule performance against the plan through EVM-type calculations.
• Probability of On-time Delivery of Critical Items. Used to show where P/p management needs
to focus attention and exercise controls based on probabilistic SRA results.
• Risk-based Completion Trend. Used to show where P/p management needs to focus attention
and exercise controls based on probabilistic SRA results over time.
• Margin Status/Sufficiency of Margin. Used to compare margin availability for key activities to
the probabilistic SRA forecasted delivery/completion dates.
• Risk-Based Tracking against the MA and ABC. Used to track the results from periodic ICSRA
against the MA and ABC.
• Confidence Level Reports. Used to communicate the confidence levels associated with possible
dates and/or costs resulting from an SRA/ICSRA (e.g. JCL).
5.7 Schedule Development Summary
Schedule development is accomplished by following the requirements and development plan in the
SMP. When complete, the P/p will have a Schedule Database contained within a scheduling tool that
has the capability to produce Schedule Outputs, including an IMS with:
• All the required Schedule Performance Measures needed to support Schedule Maintenance and
Control to produce the necessary Schedule Performance Reports
• A preliminary BoE, which provides a roadmap for Schedule Assessment and can be continually
updated through Schedule Maintenance
• An Analysis Schedule to be used for the schedule risk analyses performed in Schedule Analysis
• A Summary Schedule to support management reporting through Schedule Documentation and
Communication
148

5.8 Skills and Competencies Required for Schedule Development
The skills and competencies required for Schedule Development can be found on the SCoPe website.80
