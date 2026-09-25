# 前言

NASA/SP-20250006071
NASA
Work Breakdown
Structure (WBS)
Handbook
Christopher L Sadler
Manufacturing Technical Solutions, Inc., Huntsville AL
National Aeronautics and
Space Administration
June 2025
Page

Electronic copies are available from:
NASA STI Program: http://www.sti.nasa.gov EV Tools AdminTeam | General | Microsoft
Teams
NASA STI Information Desk
Email to: help@sti.nasa.gov/
(757) 864-9658
Write to:
NASA STI Information Desk
Mail Stop 148
NASA LaRC
Hampton, VA 23681-2199

|     |     |     |
| --- | --- | --- |

TABLE OF CONTENTS

| Table of Contents                  |     | iii  |
| ---------------------------------- | --- | ---- |
| List of Figures and Illustrations  |     | v    |
| Record of Revisions                |     | vi   |

| Preface             |     | vii  |
| ------------------- | --- | ---- |
| P.1  Purpose        |     | vii  |
| P.2  Applicability  |     | vii  |
| P.3  References     |     | vii  |

| Chapter 1:  Introduction     |     | 1   |
| ---------------------------- | --- | --- |
| 1.1  Background Information  |     | 1   |
| 1.2  Policy                  |     | 1   |

| Chapter 2:  WBS Overview  |     | 1   |
| ------------------------- | --- | --- |
| 2.1  Definition           |     | 1   |
| 2.2  WBS Hierarchy        |     | 2   |
2.2.1  Establishing and Maintaining WBS Codes in NASA’s Management Systems  5
2.2.2  Contract Work Breakdown Structure (CWBS) and CWBS Dictionary  7
2.2.3  Work Breakdown Structure Elements by Other Performing Entities  9
| 2.3  Development Guidelines  |     | 10  |
| ---------------------------- | --- | --- |
| 2.4  Summary                 |     | 10  |

| Chapter 3:  WBS Development and Control                 |     | 12  |
| ------------------------------------------------------- | --- | --- |
| 3.1  WBS and the Project Life Cycle                     |     | 12  |
| 3.2  WBS Activities and Responsibilities                |     | 13  |
| 3.3  Development Considerations                         |     | 15  |
| 3.3.1  Compatibility between WBS and CWBS               |     | 15  |
| 3.3.2  Compatibility with Internal Management Systems   |     | 16  |
| 3.3.3  Correlation with Other Requirements              |     | 17  |
| 3.3.4  Number of Levels                                 |     | 18  |
| 3.3.5  All Inclusiveness                                |     | 21  |
| 3.3.6  Change Control                                   |     | 22  |
| 3.4  WBS Development Techniques                         |     | 22  |
| 3.4.1  Preparing Functional Requirement Block Diagrams  |     | 22  |
| 3.4.2  Coding WBS Elements in a Consistent Manner       |     | 23  |
| 3.4.3  Preparing Element Tree Diagrams                  |     | 24  |
| 3.4.4  Preparing a WBS Dictionary                       |     | 26  |
| 3.4.5  Using Development Checklists                     |     | 29  |
| 3.4.6  Using WBS Templates                              |     | 30  |
| 3.5  Common Development Errors                          |     | 31  |
| 3.5.1  Using Unsuitable Former WBS                      |     | 31  |
| 3.5.2  Non-Product Elements                             |     | 31  |
| 3.5.3  Center Breakouts at Inappropriate Levels         |     | 32  |
| 3.5.4  Incorrect Element Hierarchy                      |     | 34  |
|                                                         |     |     |

|     |     |     |
| --- | --- | --- |

| Chapter 4:  WBS Uses                     |     | 36  |
| ---------------------------------------- | --- | --- |
| 4.1  Technical Management                |     | 37  |
| 4.1.1  Specification Tree                |     | 37  |
| 4.1.2  Configuration Management          |     | 37  |
| 4.1.3  Integrated Logistics Support      |     | 37  |
| 4.1.4  Test and Evaluation               |     | 38  |
| 4.2  Work Identification and Assignment  |     | 38  |
| 4.3  Schedule Management                 |     | 39  |
| 4.4  Cost Management                     |     | 40  |
| 4.5  Performance Management              |     | 41  |
| 4.6  Risk Management                     |     | 42  |

| APPENDIX A:  Acronym Listing    |     | 44  |
| ------------------------------- | --- | --- |
| APPENDIX B:  Glossary of Terms  |     | 46  |
APPENDIX C:  Standard Project WBS Level 2 Templates and WBS Dictionary Content
| Descriptions                                            |     | 47  |
| ------------------------------------------------------- | --- | --- |
| APPENDIX D:  Standard Data Requirements Document (DRD)  |     | 55  |
| APPENDIX E:  Contractor CWBS Example                    |     | 57  |

|     |     |     |
| --- | --- | --- |

List of Figures and Illustrations
2-1 Project Development Cycles and Activities……………………………………………… 2
2-2 WBS Levels Illustration…………………………………………………………. ………..4
2-3 Partial WBS with Numbering System..…………………………………………………... 5
2-4 Illustration – WBS Code Request Template for Programs/Projects…….………………... 7
2-5 Illustration – MdM Code Import Template………………………………………………. 7
2-6 WBS/CWBS Relationship………………………………………………………………... 9
3-1 WBS and the Project Life Cycle..……………………………………………………….. 12
3-2 WBS Product and Enabling Support Content…………………………….….………….. 13
3-3 WBS Development Activities & Responsibilities..………………………….………….. 15
3-4 WBS Relational Interfaces to NASA Business/Management Systems…………………. 17
3-5 WBS Cross-Reference Matrix……………………………………………….………….. 18
3-6 WBS Hierarchy Illustration………………………………………………….………….. 19
3-7 Relationships between WBS, OBS, CA, WP, and PP……………………….………….. 21
3-8 Agency WBS Numbering System...…………………………………………………….. 22
3-9 Workaround for WBS Level 7 Limitations …………………….……..………………... 24
3-10 Partial WBS Tree Diagram Illustrating Recommended Practices……..………………... 25
3-11 Sample Software WBS Illustration……..……………………………………………….. 26
3-12 Example – WBS Index Excerpt………………………………………………................. 27
3-13 WBS Dictionary Example…………………………………………………….................. 29
3-14 WBS Checklist Example…………………………………………………………………30
3-15 Unsuitable Non-Product, Phase-Oriented WBS………………………………………… 32
3-16 Unsuitable Functional/Organizational Oriented WBS..……………………..…………... 32
3-17 Center Breakout Guidance for a WBS…………………………………………………... 34
3-18 Illustration of Incorrect Element Hierarchy……………………………………………... 35
4-1 The WBS as a Project Management Tool for Integration…...…………………………... 36
4-2 Responsibility Assignment Matrix (RAM)……………………………………………… 39
4-3 WBS and the Development of the Performance Measurement Baseline……………….. 42
4-4 WBS Serves as a Common Reference Point in Risk Management………………….….. 43

|     |     |     |     |     |
| --- | --- | --- | --- | --- |

Record of Revisions
| REV  | DESCRIPTION  |     | DATE  |     |
| ---- | ------------ | --- | ----- | --- |
LTR
|     | Basic Issue                    |     | January 2010    |     |
| --- | ------------------------------ | --- | --------------- | --- |
| A   | Miscellaneous Minor Revisions  |     | October 2016    |     |
| B   | Miscellaneous Minor Revisions  |     | January 2018    |     |
| C   | Miscellaneous Minor Revisions  |     | September 2019  |     |
| D   | Miscellaneous Minor Revisions  |     | November 2021   |     |
June 2025
| E   | Miscellaneous Minor Revisions  |     |     |     |
| --- | ------------------------------ | --- | --- | --- |

|     |     |     |     |     |
| --- | --- | --- | --- | --- |

Preface
P.1 Purpose
The purpose of this document is to provide program/project teams necessary instruction and
guidance in the best practices for Work Breakdown Structure (WBS) and WBS dictionary
development and use for project implementation and management control. This handbook can be
used for all types of NASA projects and work activities including research, development,
construction, test and evaluation, and operations. The products of these work efforts may be
hardware, software, data, or service elements (alone or in combination). The aim of this document
is to assist project teams in the development of effective WBSs that provide a framework of
common reference for all project elements.
The WBS and WBS dictionary are effective management processes for planning, organizing, and
administering NASA programs and projects. The guidance contained in this document is
applicable to both in-house, NASA-led and contractor projects. It assists management teams from
both entities in fulfilling necessary responsibilities for successful accomplishment of project cost,
schedule, and technical goals.
Benefits resulting from the use of an effective WBS include, but are not limited to: providing a
basis for assigned project responsibilities, providing a basis for project schedule and budget
development, simplifying a project by dividing the total work scope into manageable units, and
providing a common reference for all project communication.
P.2 Applicability
This handbook provides WBS and WBS dictionary development guidance for NASA
Headquarters, NASA Centers, inter-government partners, academic institutions, international
partners, and contractors to the extent specified in the contract or agreement.
P.3 References
NPD 7120.4, NASA Engineering and Program/Project Management Policy
NFS Part 1834, Major Systems Acquisition
Electronic Industries Alliance (EIA)-748, Earned Value Management Systems Standard
NPR 7120.5, NASA Space Flight Program and Project Management Requirements
NPR 7120.8, NASA Research and Technology Program and Project Management Requirements
MIL-STD-881, Department of Defense Standard Practice, Work Breakdown Structures for
Defense Materiel Items
PMI 978-1-62825-619-2, Practice Standard for Work Breakdown Structures
NASA Space Flight Program and Project Management Handbook
NASA Systems Engineering Handbook
