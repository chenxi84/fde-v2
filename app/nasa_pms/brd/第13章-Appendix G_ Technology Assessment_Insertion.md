# Appendix G: Technology Assessment/Insertion

G.1 Introduction, Purpose, a complex process that is often dealt with in an ad
and Scope hoc manner differing greatly from project to project
with varying degrees of success.
In 2014, the Headquarters Office of Chief Engineer
and Office of Chief Technologist conducted an Technology infusion frequently results in schedule
Agency-wide study on Technical Readiness Level slips, cost overruns, and occasionally even in cancel-
(TRL) usage and Technology Readiness Assessment lations or failures. In post mortem, the root cause of
(TRA) implementation. Numerous findings, observa- such events is often attributed to “inadequate defi-
tions, and recommendations were identified, as was a nition of requirements.” If such is indeed the root
wealth of new guidance, best practices, and clarifica- cause, then correcting the situation is simply a matter
tions on how to interpret TRL and perform TRAs. of defining better requirements, but this may not be
These are presently being collected into a NASA TRA the case—at least not totally.
Handbook (in work), which will replace this appendix.
In the interim, contact HQ/Steven Hirshorn on any In fact, there are many contributors to schedule
specific questions on interpretation and application of slip, cost overrun, and project cancellation and fail-
TRL/TRA. Although the information contained in ure—among them lack of adequate requirements
this appendix may change, it does provide some infor- definition. The case can be made that most of these
mation until the TRA Handbook can be completed. contributors are related to the degree of uncertainty
at the outset of the project and that a dominant factor
Agency programs and projects frequently require in the degree of uncertainty is the lack of understand-
the development and infusion of new technologi- ing of the maturity of the technology required to
cal advances to meet mission goals, objectives, and bring the project to fruition and a concomitant lack
resulting requirements. Sometimes the new techno- of understanding of the cost and schedule reserves
logical advancement being infused is actually a heri- required to advance the technology from its present
tage system that is being incorporated into a different state to a point where it can be qualified and suc-
architecture and operated in a different environment cessfully infused with a high degree of confidence.
from that for which it was originally designed. It is Although this uncertainty cannot be eliminated, it
important to recognize that the adaptation of heritage can be substantially reduced through the early appli-
systems frequently requires technological advance- cation of good systems engineering practices focused
ment. Failure to account for this requirement can on understanding the technological requirements;
result in key steps of the development process being the maturity of the required technology; and the
given short shrift—often to the detriment of the technological advancement required to meet pro-
program/project. In both contexts of technological gram/project goals, objectives, and requirements.
advancement (new and adapted heritage), infusion is
206

TABLE G.1-1 Products Provided by the TA as a Function of Program/Project Phase
Gate Product
KDP A: Transition from Requires an assessment of potential technology needs versus current and planned
Pre-Phase A to Phase A technology readiness levels, as well as potential opportunities to use commercial,
academic, and other government agency sources of technology. Included as part of
the draft integrated baseline. Technology Development Plan is baselined that identifies
technologies to be developed, heritage systems to be modified, alternative paths to be
pursued, fallback positions and corresponding performance descopes, milestones, metrics,
and key decision points. Initial Technology Readiness Assessment (TRA) is available.
KDP B: Transition from Technology Development Plan and Technology Readiness Assessment (TRA) are updated.
Phase A to Phase B Incorporated in the preliminary project plan.
KDP C: Transition from Requires a TRAR demonstrating that all systems, subsystems, and components have
Phase B to Phase C/D achieved a level of technological maturity with demonstrated evidence of qualification in a
relevant environment.
Source: NPR 7120 .5 .
A number of processes can be used to develop the systems, subsystems, and components demonstrated
appropriate level of understanding required for through test and analysis. The initial AD2 provides the
successful technology insertion. The intent of this material necessary to develop preliminary cost and to
appendix is to describe a systematic process that schedule plans and preliminary risk assessments. In
can be used as an example of how to apply standard subsequent assessments, the information is used to
systems engineering practices to perform a compre- build the Technology Development Plan and in the
hensive Technology Assessment (TA). The TA com- process, identify alternative paths, fallback positions,
prises two parts, a Technology Maturity Assessment and performance descope options. The information
(TMA) and an Advancement Degree of Difficulty is also vital to preparing milestones and metrics for
Assessment (AD2). The process begins with the TMA subsequent Earned Value Management (EVM).
which is used to determine technological maturity
via NASA’s Technology Readiness Level (TRL) scale. The TMA is performed against the hierarchical
It then proceeds to develop an understanding of what breakdown of the hardware and software products
is required to advance the level of maturity through of the program/project PBS to achieve a systematic,
the AD2. It is necessary to conduct TAs at various overall understanding at the system, subsystem, and
stages throughout a program/project to provide the component levels. (See FIGURE G.1-1.)
Key Decision Point (KDP) products required for
transition between phases. (See TABLE G.1-1.)
G.2 Inputs/Entry Criteria
The initial TMA provides the baseline maturity of It is extremely important that a TA process be defined
the system’s required technologies at program/project at the beginning of the program/project and that it
outset and allows monitoring progress throughout be performed at the earliest possible stage (concept
development. The final TMA is performed just prior development) and throughout the program/proj-
to the Preliminary Design Review (PDR). It forms ect through PDR. Inputs to the process will vary in
the basis for the Technology Readiness Assessment level of detail according to the phase of the program/
Report (TRAR), which documents the maturity project, and even though there is a lack of detail in
of the technological advancement required by the Pre-Phase A, the TA will drive out the major critical
207

1.3
Crew Launch
Vehicle
1.3.8
Launch
Vehicle
...
1.3.8.1 1.3.8.2 1.3.8.3
First Stage Upper Stage Upper Stage
Engine
... ...
1.3.8.2.4 1.3.8.2.5 1.3.8.2.6 1.3.8.2.7 1.3.8.2.8 1.3.8.2.9 1.3.8.2.10
MPS US RCS FS RCS TVCS Avionics Software Integrated
T.e..st H/W
.1: Integ MPS .1: Integ RCS .1: Integ RCS .1: Integ TVCS .1: Integ Avionics .1: Integ S/W .1: MPTA
System
.2: LH System .2: Integ Energy .2: Actuator .2: C&DH System .2: GVT
Support .2: Flight S/W
.3: O2 Fluid Sys. .3: Hydraulic .3: GN&C H/W .3: STA
Power
.4: Pressure & .4: Radio Frequency .4: US for DTF-1
Pneumatic Sys. .4: APU System
.5: US for VTF-2
.5: Umbilicals & .5: EPS
.6: US for RRF-3
Disconnect
.6: Electrical Integration
.7: Struc. Thermal
.7: Develop Flight Instrument Component Test
.8: Sensor & Instrument System
.9: EGSE
.10: Integ CLV Avionics System
Element Testing
.11: Flight Safety System
FIGURE G.1-1 PBS Example
G.3 How to Do Technology
technological advancements required. Therefore, at
the beginning of Pre-Phase A, the following should Assessment
be provided:
The technology assessment process makes use of basic
• Refinement of TRL definitions. systems engineering principles and processes. As
• Definition of AD2. mentioned previously, it is structured to occur within
• Definition of terms to be used in the assessment the framework of the Product Breakdown Structure
process. (PBS) to facilitate incorporation of the results. Using
• Establishment of meaningful evaluation criteria the PBS as a framework has a twofold benefit—it
and metrics that will allow for clear identification breaks the “problem” down into systems, subsys-
of gaps and shortfalls in performance. tems, and components that can be more accurately
• Establishment of the TA team. assessed; and it provides the results of the assessment
• Establishment of an independent TA review team. in a format that can be readily used in the generation
208

of program costs and schedules. It can also be highly TMA and is used to develop the TRAR, which val-
beneficial in providing milestones and metrics for idates that all elements are at the requisite maturity
progress tracking using EVM. As discussed above, it level. (See FIGURE G.3-1.)
is a two-step process comprised of (1) the determina-
tion of the current technological maturity in terms Even at the conceptual level, it is important to use
of TRLs and (2) the determination of the difficulty the formalism of a PBS to avoid allowing important
associated with moving a technology from one TRL technologies to slip through the cracks. Because of
to the next through the use of the AD2. the preliminary nature of the concept, the systems,
subsystems, and components will be defined at a level
Conceptual Level Activities that will not permit detailed assessments to be made.
The overall process is iterative, starting at the concep- The process of performing the assessment, however,
tual level during program Formulation, establishing is the same as that used for subsequent, more detailed
the initial identification of critical technologies, and steps that occur later in the program/project where
establishing the preliminary cost, schedule, and risk systems are defined in greater detail.
mitigation plans. Continuing on into Phase A, the
process is used to establish the baseline maturity, the Architectural Studies
Technology Development Plan, and the associated Once the concept has been formulated and the ini-
costs and schedule. The final TA consists only of the tial identification of critical technologies made, it is
Identify systems, sub- Assign TRL to subsystems
Assign TRL to all
systems, and components based on lowest TRL of
components based on
per hierarchical product components and TRL
assessment of maturity
breakdown of the WBS state of integration
Identify all components, Assign TRL to systems
Baseline technology subsystems, and systems based on lowest TRL of
maturity assessment that are at lower TRLs subsystems and TRL
than required by program state of integration
Perform AD2 on all
components, subsystems,
and systems that are below
requisite maturity level
Technology Development Plan
Cost Plan
Schedule Plan
Risk Assessment
FIGURE G.3-1 Technology Assessment Process
209

necessary to perform detailed architecture studies 1980s. The TRL essentially describes the state of a
with the Technology Assessment Process intimately given technology and provides a baseline from which
interwoven. (See FIGURE G.3-2.) maturity is gauged and advancement defined. (See
FIGURE G.4-1.)
Require- Architectural System
Concepts
ments Studies Design Programs are often undertaken without fully under-
standing either the maturity of key technologies
TRL/AD2 Assessment or what is needed to develop them to the required
level. It is impossible to understand the magnitude and
Technology Maturation scope of a development program without having a clear
understanding of the baseline technological maturity of
FIGURE G.3-2 Architectural Studies and Technology all elements of the system. Establishing the TRL is a
Development
vital first step on the way to a successful program. A
frequent misconception is that in practice, it is too
The purpose of the architecture studies is to refine difficult to determine TRLs and that when you do,
end-item system design to meet the overall scientific it is not meaningful. On the contrary, identifying
requirements of the mission. It is imperative that TRLs can be a straightforward systems engineering
there be a continuous relationship between architec- process of determining what was demonstrated and
tural studies and maturing technology advances. The under what conditions it was demonstrated.
architectural studies should incorporate the results of
the technology maturation, planning for alternative Terminology
paths and identifying new areas required for devel- At first glance, the TRL descriptions in FIGURE G.4-1
opment as the architecture is refined. Similarly, it appear to be straightforward. It is in the process of
is incumbent upon the technology maturation pro- trying to assign levels that problems arise. A primary
cess to identify requirements that are not feasible cause of difficulty is in terminology; e.g., everyone
and development routes that are not fruitful and to knows what a breadboard is, but not everyone has
transmit that information to the architecture studies the same definition. Also, what is a “relevant envi-
in a timely manner. It is also incumbent upon the ronment?” What is relevant to one application may
architecture studies to provide feedback to the tech- or may not be relevant to another. Many of these
nology development process relative to changes in terms originated in various branches of engineering
requirements. Particular attention should be given and had, at the time, very specific meanings to that
to “heritage” systems in that they are often used in particular field. They have since become commonly
architectures and environments different from those used throughout the engineering field and often
in which they were designed to operate. acquire differences in meaning from discipline to
discipline, some differences subtle, some not so sub-
tle. “Breadboard,” for example, comes from electrical
G.4 Establishing TRLs
engineering where the original use referred to check-
A Technology Readiness Level (TRL) is, at its most ing out the functional design of an electrical circuit
basic, a description of the performance history of a by populating a “breadboard” with components to
given system, subsystem, or component relative to verify that the design operated as anticipated. Other
a set of levels first described at NASA HQ in the terms come from mechanical engineering, referring
210

System test, launch,
TRL 9 Actual system “flight proven” through successful
and operations
__ mission operations
TRL 8 Actual system completed and “flight qualified”” through
System/subsystem
__ test and demonstration (ground or flight)
development
TRL 7 System prototype demonstration in a
target/space environment
__
Technology
demonstration
TRL 6 System/subsystem model or prototype demonstration
__ in a relevant environment (ground or space)
TRL 5 Component and/or breadboard validation in relevant
Technology
__ environment
development
TRL 4 Component and/or breadboard validation in laboratory
__ environment
Research to prove
feasibility
TRL 3 Analytical and experimental critical function and/or
__ characteristic proof-of-concept
Basic technology
research TRL 2 Technology concept and/or application formulated
__
TRL 1 Basic principles observed and reported
FIGURE G.4-1 Technology Readiness Levels
primarily to units that are subjected to different levels with clear definitions, judgment calls will be required
of stress under testing, e.g., qualification, protoflight, when it comes time to assess just how similar a given
and flight units. The first step in developing a uni- element is relative to what is needed (i.e., is it close
form TRL assessment (see FIGURE G.4-2) is to define enough to a prototype to be considered a proto-
the terms used. It is extremely important to develop type, or is it more like an engineering breadboard?).
and use a consistent set of definitions over the course Describing what has been done in terms of form, fit,
of the program/project. and function provides a means of quantifying an
element based on its design intent and subsequent
Judgment Calls performance. The current definitions for software
Having established a common set of terminology, it TRLs are contained in NPR 7123.1, NASA Systems
is necessary to proceed to the next step: quantifying Engineering Processes and Requirements.
“judgment calls” on the basis of past experience. Even
211

Assessment Team
Has an identical unit been successfully
YES
A third critical element of any assessment relates to operated/launched in identical TRL 9
configuration/environment?
the question of who is in the best position to make
NO
judgment calls relative to the status of the technol-
ogy in question. For this step, it is extremely import-
Has an identical unit in a different configuration/
ant to have a well-balanced, experienced assessment system architecture been successfully operated
YES
in space or the target environment or launched? TRL 5
team. Team members do not necessarily have to be
If so, then this initially drops to TRL 5 until
discipline experts. The primary expertise required for differences are evaulated.
a TRL assessment is that the systems engineer/user NO
understands the current state of the art in applica-
Has an identical unit been flight qualified but YES
tions. User considerations are evaluated by HFE per- TRL 8
not yet operated in space or the target
sonnel who understand the challenges of technology environment or launched?
insertions at various stages of the product life cycle. NO
Having established a set of definitions, defined a pro-
Has a prototype unit (or one similar enough to be
YES
cess for quantifying judgment calls, and assembled an considered a prototype) been successfully operated TRL 7
in space or the target environment or launched?
expert assessment team, the process primarily consists
of asking the right questions. The flowchart depicted NO
in FIGURE G.4-2 demonstrates the questions to ask to
Has a prototype unit (or one similar enough
YES
determine TRL at any level in the assessment. to be considered a prototype) been TRL 6
demonstrated in a relevant environment?
Heritage Systems NO
Note the second box particularly refers to heritage Has a breadboard unit been demonstrated in YES
TRL 5
systems. If the architecture and the environment a relevant environment?
have changed, then the TRL drops to TRL 5—at NO
least initially. Additional testing may need to be done
Has a breadboard unit been demonstrated in YES
TRL 4
for heritage systems for the new use or new environ- a laboratory environment?
ment. If in subsequent analysis the new environment NO
is sufficiently close to the old environment or the new
Has analytical and experimental YES
TRL 3
architecture sufficiently close to the old architecture, proof-of-concept been demonstrated?
then the resulting evaluation could be TRL 6 or 7, NO
but the most important thing to realize is that it is
Has concept or application YES
no longer at TRL 9. Applying this process at the TRL 2
been formulated?
system level and then proceeding to lower levels of
NO
subsystem and component identifies those elements
Have basic principles been observed YES
that require development and sets the stage for the TRL 1
and reported?
subsequent phase, determining the AD2.
NO
RETHINK POSITION REGARDING
THIS TECHNOLOGY!
FIGURE G.4-2 TMA Thought Process
212

Formal Process for Determining TRLs the system is at TRL 2. The problem of multiple ele-
A method for formalizing this process is shown in ments being at low TRLs is dealt with in the AD2
FIGURE G.4-3. Here, the process has been set up as a process. Note that the issue of integration affects the
table: the rows identify the systems, subsystems, and TRL of every system, subsystem, and component. All
components that are under assessment. The columns of the elements can be at a higher TRL, but if they
identify the categories that will be used to determine have never been integrated as a unit, the TRL will
the TRL; i.e., what units have been built, to what be lower for the unit. How much lower depends on
scale, and in what environment have they been tested. the complexity of the integration. The assessed com-
Answers to these questions determine the TRL of an plexity depends upon the combined judgment of the
item under consideration. The TRL of the system is engineers. It is important to have a good cross-section
determined by the lowest TRL present in the system; of senior people sitting in judgment.
i.e., a system is at TRL 2 if any single element in
Red = Below TRL 3
Yellow = TRL 3, 4 & 5
Green = TRL 6 and above
White = Unknown
X = Exists
213
tpecnoC
Demonstration Units Environment Unit Description
draobdaerB draobssarB
ledoM
latnempoleveD
epygotorP
defiilauQ
thgilF
tnemnorivnE
yrotarobaL
tnemnorivnE
tnaveleR
tnemnorivnE
ecapS
noitarepO
hcnuaL
ecapS mroF
tiF
noitcnuF
elacS
eatairporppA
LRT
llarevO
1.0 System
1.1 Subsystem X
1.1.1 Mechanical Components
1.1.2 Mechanical Systems
1.1.3 Electrical Components X X X X X
1.1.4 Electrical Systems
1.1.5 Control Systems
1.1.6 Thermal Systems X X X
1.1.7 Fluid Systems X
1.1.8 Optical Systems
1.1.9 Electro-Optical Systems
1.1.10 Software Systems
1.1.11 Mechanisms X
1.1.12 Integration
1.2 Subsystem Y
1.2.1 Mechanical Components
FIGURE G.4-3 TRL Assessment Matrix
