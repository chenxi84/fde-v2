# Appendix L: Interface Requirements

Document Outline
1.0 Introduction 3.0 Interfaces
1.1 Purpose and Scope 3.1 General
State the purpose of this document and briefly iden- In the subsections that follow, provide the detailed descrip-
tify the interface to be defined. (For example, “This tion, responsibilities, coordinate systems, and numerical
IRD defines and controls the interface(s) requirements requirements as they relate to the interface plane.
between ______ and ______.”)
3.1.1 Interface Description
1.2 Precedence Describe the interface as defined in the system specifi-
Define the relationship of this document to other pro- cation. Use tables, figures, or drawings as appropriate.
gram documents and specify which is controlling in the
event of a conflict. 3.1.2 Interface Responsibilities
Define interface hardware and interface boundary
1.3 Responsibility and Change responsibilities to depict the interface plane. Use tables,
Authority figures, or drawings as appropriate.
State the responsibilities of the interfacing organiza-
tions for development of this document and its contents. 3.1.3 Coordinate Systems
Define document approval authority (including change Define the coordinate system used for interface require-
approval authority). ments on each side of the interface. Use tables, figures, or
drawings as appropriate.
2.0 Documents
3.1.4 E ngineering Units, Tolerances, and
2.1 Applicable Documents Conversion
List binding documents that are invoked to the extent Define the measurement units along with tolerances.
specified in this IRD. The latest revision or most recent If required, define the conversion between measure-
version should be listed. Documents and requirements ment systems.
imposed by higher-level documents (higher order of pre-
cedence) should not be repeated. 3.2 Interface Requirements
In the subsections that follow, define structural limiting
2.2 Reference Documents values at the interface, such as interface loads, forcing
List any document that is referenced in the text in this functions, and dynamic conditions. Define the interface
subsection. requirements on each side of the interface plane.
236

Appendix L: Interface RequirementsDocument Outline
3.2.1 Mass Properties example, this subsection should cover various data stan-
Define the derived interface requirements based on the dards, message timing, protocols, error detection/correc-
allocated requirements contained in the applicable speci- tion, functions, initialization, and status.
fication pertaining to that side of the interface. For exam-
ple, this subsection should cover the mass of the element. 3.2.7 Environments
Define the derived interface requirements based on
3.2.2 Structural/Mechanical the allocated requirements contained in the applicable
Define the derived interface requirements based on specification pertaining to that side of the interface. For
the allocated requirements contained in the applicable example, cover the dynamic envelope measures of the ele-
specification pertaining to that side of the interface. For ment in English units or the metric equivalent on this
example, this subsection should cover attachment, stiff- side of the interface.
ness, latching, and mechanisms.
3.2.7.1 Electromagnetic Effects
3.2.3 Fluid 3.2.7.1.a Electromagnetic Compatibility
Define the derived interface requirements based on Define the appropriate electromagnetic compatibility
the allocated requirements contained in the applicable requirements. For example, the end-item-1-to-end-item-2
specification pertaining to that side of the interface. For interface shall meet the requirements [to be determined]
example, this subsection should cover fluid areas such as of systems requirements for electromagnetic compatibility.
thermal control, O and N , potable and waste water,
2 2
fuel cell water, and atmospheric sampling. 3.2.7.1.b Electromagnetic Interference
Define the appropriate electromagnetic interference
3.2.4 Electrical (Power) requirements. For example, the end-item-1-to-end-
Define the derived interface requirements based on item-2 interface shall meet the requirements [to be
the allocated requirements contained in the applicable determined] of electromagnetic emission and susceptibil-
specification pertaining to that side of the interface. For ity requirements for electromagnetic compatibility.
example, this subsection should cover various electric
current, voltage, wattage, and resistance levels. 3.2.7.1.c Grounding
Define the appropriate grounding requirements. For exam-
3.2.5 Electronic (Signal) ple, the end-item-1-to-end-item-2 interface shall meet the
Define the derived interface requirements based on requirements [to be determined] of grounding requirements.
the allocated requirements contained in the applicable
specification pertaining to that side of the interface. For 3.2.7.1.d Bonding
example, this subsection should cover various signal types Define the appropriate bonding requirements. For
such as audio, video, command data handling, and example, the end-item-1-to-end-item-2 structural/
navigation. mechanical interface shall meet the requirements [to be
determined] of electrical bonding requirements.
3.2.6 Software and Data
Define the derived interface requirements based on 3.2.7.1.e Cable and Wire Design
the allocated requirements contained in the applicable Define the appropriate cable and wire design require-
specification pertaining to that side of the interface. For ments. For example, the end-item-1-to-end-item-2
237

Appendix L: Interface RequirementsDocument Outline
cable and wire interface shall meet the requirements [to 3.2.7.4 Vibroacoustics
be determined] of cable/wire design and control require- Define the appropriate vibroacoustics requirements.
ments for electromagnetic compatibility. Define the vibroacoustic loads that each end item should
accommodate.
3.2.7.2 Acoustic
Define the appropriate acoustics requirements. Define 3.2.7.5 Human Operability
the acoustic noise levels on each side of the interface in Define the appropriate human interface requirements.
accordance with program or project requirements. Define the human-centered design considerations, con-
straints, and capabilities that each end item should
3.2.7.3 Structural Loads accommodate.
Define the appropriate structural loads requirements. Define
the mated loads that each end item should accommodate. 3.2.8 Other Types of Interface Requirements
Define other types of unique interface requirements that
may be applicable.
238
