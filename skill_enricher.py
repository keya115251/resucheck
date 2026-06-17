"""
skill_enricher.py
-----------------
Step 4: Semantic skill enrichment and evidence scoring.

What this does:
    1. Collects all skills explicitly listed in the SKILLS section
    2. Scans project descriptions + experience bullets for implied skills
       using cosine similarity against a skills taxonomy
    3. Cross-references to produce:
         - evidenced   : skills that appear in OR are implied by project/exp text
         - listed_only : skills mentioned in SKILLS section with no project evidence
         - implied     : skills found in project text but NOT listed by the candidate

Input  : entities dict from entity_extractor.extract_entities()
Output : enriched dict — original entities + new "skill_analysis" key
"""

import re
from sentence_transformers import SentenceTransformer, util


# ── Skills taxonomy ───────────────────────────────────────────────────────────

SKILLS_TAXONOMY = [
    # Programming languages
    "Python", "C++", "C", "Java", "JavaScript", "TypeScript", "Go", "Rust",
    "SQL", "Bash", "Shell Scripting", "R", "MATLAB", "Scala", "Kotlin", "Swift",
    "HTML", "CSS", "PHP", "Ruby", "Dart", "Assembly",

    # ML / DL frameworks
    "PyTorch", "TensorFlow", "Keras", "scikit-learn", "XGBoost", "LightGBM",
    "HuggingFace Transformers", "ONNX", "TensorRT", "JAX", "MXNet",

    # NLP
    "NLP", "Named Entity Recognition", "Text Classification", "Sentiment Analysis",
    "Machine Translation", "spaCy", "NLTK", "LangChain", "Llama Index",
    "BERT", "GPT", "DistilBERT", "RoBERTa", "T5", "Word2Vec", "FastText",
    "Transfer Learning", "Fine-tuning", "RAG", "Embeddings",

    # Computer Vision
    "Computer Vision", "Object Detection", "Image Segmentation",
    "OpenCV", "YOLOv8", "YOLO", "Detectron2", "MONAI",
    "Image Classification", "Semantic Segmentation", "Instance Segmentation",
    "Real-Time Inference", "TensorRT Optimization",

    # Web / Full-stack
    "React", "Node.js", "Express", "Django", "Flask", "FastAPI",
    "Vue.js", "Angular", "Spring Boot", "REST API", "GraphQL",
    "HTML/CSS", "Bootstrap", "Tailwind CSS", "Next.js",

    # Mobile
    "Android Development", "iOS Development", "React Native", "Flutter",

    # Databases
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "SQLite", "Firebase", "Cassandra", "Oracle DB",

    # DevOps / Cloud / Infrastructure
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "CI/CD",
    "Jenkins", "GitHub Actions", "Terraform", "Linux", "Nginx",
    "MLflow", "Weights & Biases", "Model Deployment",

    # Data engineering
    "Pandas", "NumPy", "Data Preprocessing", "Feature Engineering",
    "ETL", "Data Pipeline", "Apache Spark", "Kafka", "Airflow",
    "Power BI", "Tableau", "Excel", "Data Visualization",

    # Systems / CS fundamentals
    "Distributed Systems", "System Design", "Microservices",
    "Operating Systems", "Computer Networks", "Database Management",
    "Data Structures", "Algorithms", "Object Oriented Programming",
    "Compiler Design", "Computer Architecture",

    # General ML concepts
    "Deep Learning", "Machine Learning", "Reinforcement Learning",
    "Model Optimization", "Quantization", "Pruning", "Distillation",
    "Semantic Similarity", "Information Retrieval",

    # Mechanical engineering — CAD / simulation
    "SolidWorks", "AutoCAD", "CATIA", "Fusion 360", "Creo", "Inventor",
    "ANSYS Mechanical", "ANSYS Fluent", "ANSYS", "COMSOL Multiphysics",
    "Abaqus", "HyperMesh", "MATLAB Simulink", "OpenRocket",
    # Mechanical — analysis
    "Finite Element Analysis", "Computational Fluid Dynamics", "CFD",
    "Thermal Analysis", "Structural Analysis", "Fatigue Analysis",
    "Vibration Analysis", "Heat Transfer", "Fluid Mechanics",
    "Thermodynamics", "Dynamics", "Kinematics",
    # Mechanical — manufacturing
    "Manufacturing Processes", "CNC Machining", "3D Printing", "Additive Manufacturing",
    "Injection Moulding", "Sheet Metal Fabrication", "Welding", "Casting",
    "GD&T", "Tolerance Analysis", "Quality Control", "Lean Manufacturing",
    "Six Sigma", "Process Optimization",
    # Mechanical — materials
    "Material Science", "Composite Materials", "Failure Analysis",
    "Non-Destructive Testing", "Metallurgy",

    # Civil engineering — structural
    "STAAD Pro", "SAP2000", "ETABS", "SAFE", "TEKLA", "Revit Structure",
    "AutoCAD Civil 3D", "Civil 3D", "Revit",
    "Structural Design", "RCC Design", "Steel Structure Design",
    "Foundation Design", "Earthquake Engineering", "Wind Load Analysis",
    # Civil — geotechnical
    "Geotechnical Engineering", "Soil Mechanics", "Ground Improvement",
    "Pile Foundation", "Retaining Wall Design",
    # Civil — transportation and surveying
    "Surveying", "Total Station", "GPS Surveying", "GIS", "ArcGIS",
    "Highway Design", "Traffic Engineering", "Pavement Design",
    # Civil — construction
    "Construction Management", "Project Planning", "MS Project", "Primavera",
    "Bill of Quantities", "Cost Estimation", "Building Information Modelling",

    # Electrical engineering — power systems
    "Power Systems", "Power Electronics", "Electric Machines",
    "Transformers", "Switchgear", "Protection Relays",
    "ETAP", "PSCAD", "PowerWorld", "Load Flow Analysis",
    "High Voltage Engineering", "Renewable Energy Systems",
    "Solar PV Design", "Wind Energy", "Smart Grid",
    # Electrical — drives and control
    "Motor Control", "Variable Frequency Drive", "PLC Programming",
    "SCADA", "PID Control", "Control Systems",
    "MATLAB Control Toolbox", "Simulink",
    # Electrical — measurement
    "Instrumentation", "Sensors", "Data Acquisition", "LabVIEW",
    "Oscilloscope", "Multimeter", "Signal Conditioning",

    # Electronics — analog and digital
    "Circuit Design", "Analog Circuit Design", "Digital Circuit Design",
    "PCB Design", "Altium Designer", "KiCad", "Eagle",
    "Operational Amplifiers", "Filter Design", "RF Design",
    "Signal Processing", "Digital Signal Processing", "FFT",
    "FPGA", "Verilog", "VHDL", "Xilinx", "Intel Quartus",
    # Electronics — embedded
    "Embedded Systems", "Microcontrollers", "Arduino", "Raspberry Pi",
    "ESP32", "STM32", "PIC", "AVR", "ARM Cortex",
    "RTOS", "FreeRTOS", "Bare Metal Programming",
    "UART", "SPI", "I2C", "CAN Bus", "Modbus",
    "Sensor Integration", "Actuator Control", "Interrupt Handling",
    # Electronics — communication
    "Wireless Communication", "Bluetooth", "Zigbee", "LoRa", "Wi-Fi",
    "5G", "LTE", "OFDM", "Antenna Design",

    # IoT
    "IoT", "IoT Architecture", "Edge Computing", "MQTT", "CoAP",
    "AWS IoT", "Azure IoT Hub", "Google Cloud IoT",
    "Node-RED", "ThingsBoard", "Home Automation",
    "Wearable Devices", "Industrial IoT", "Predictive Maintenance",

    # Biotechnology
    "Bioinformatics", "Genomics", "Proteomics", "Transcriptomics",
    "DNA Sequencing", "PCR", "CRISPR", "Gene Editing",
    "Cell Culture", "Fermentation", "Bioprocess Engineering",
    "BLAST", "NCBI", "Biopython", "R Bioconductor",
    "Molecular Docking", "Drug Discovery", "Clinical Trials",
    "Biostatistics", "Flow Cytometry", "Gel Electrophoresis",
    "ELISA", "Western Blot", "Microscopy",
    "Protein Structure Prediction", "AlphaFold",

    # IT — networking and infrastructure
    "Networking", "TCP/IP", "DNS", "DHCP", "VPN",
    "Cisco", "Wireshark", "Network Security", "Firewall",
    "Active Directory", "Windows Server", "Linux Administration",
    "Virtualization", "VMware", "Hyper-V",
    "IT Support", "Help Desk", "ITIL", "ServiceNow",
    # IT — ERP and enterprise
    "SAP", "SAP ERP", "SAP HANA", "Oracle ERP",
    "Salesforce", "Microsoft Dynamics",
    # IT — software testing
    "Software Testing", "Manual Testing", "Automation Testing",
    "Selenium", "JUnit", "TestNG", "Postman", "JMeter",
    "Test Case Design", "Bug Tracking", "JIRA",

    # Cybersecurity
    "Cybersecurity", "Network Security", "Application Security",
    "Penetration Testing", "Ethical Hacking", "Vulnerability Assessment",
    "Nmap", "Metasploit", "Burp Suite", "Wireshark", "Kali Linux",
    "OWASP", "SQL Injection", "XSS", "CSRF",
    "Cryptography", "PKI", "SSL/TLS", "AES", "RSA",
    "SIEM", "Splunk", "Security Operations", "Incident Response",
    "Malware Analysis", "Reverse Engineering", "CTF",
    "Cloud Security", "Zero Trust", "IAM",
    "Digital Forensics", "Threat Intelligence",

    # CSE — algorithms and theory
    "Data Structures", "Algorithms", "Dynamic Programming",
    "Graph Algorithms", "Competitive Programming",
    "Complexity Analysis", "Formal Languages", "Automata Theory",
    # CSE — software engineering
    "Object Oriented Programming", "Design Patterns", "SOLID Principles",
    "Agile", "Scrum", "Software Architecture", "Clean Code",
    "Version Control", "Code Review", "Unit Testing",
    # CSE — operating systems and networks
    "Operating Systems", "Process Management", "Memory Management",
    "Computer Networks", "Socket Programming", "HTTP", "WebSockets",
    "Compiler Design", "Computer Architecture", "Assembly Language",

    # Tools
    "Git", "Jupyter", "VS Code", "ROS", "ROS2",
    "Postman", "Figma", "Jira", "Notion", "Latex",
]


# ── Implicit evidence whitelist ───────────────────────────────────────────────
# These skills are foundational dev tools — if someone has substantive ML
# projects, they're implicitly evidenced regardless of whether they appear
# verbatim in a project description. Flagging them as "listed only" is noise.

IMPLICIT_EVIDENCE = {
    # Programming
    "python", "git", "linux", "bash", "jupyter", "vs code", "sql",
    "numpy", "pandas", "shell scripting", "excel",
    "html", "css", "html/css", "c", "c++", "java",
    # Engineering tools always present if doing the field
    "autocad", "matlab", "solidworks", "matlab simulink",
    "arduino", "raspberry pi",
    # CS fundamentals
    "data structures", "algorithms", "object oriented programming",
    "operating systems", "computer networks",
}


# ── Model loader (singleton) ──────────────────────────────────────────────────

_model = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("Loading sentence-transformers model (first run only)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Model loaded.")
    return _model


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flatten_listed_skills(skills_dict: dict) -> list[str]:
    flat = []
    for items in skills_dict.values():
        flat.extend(items)
    return list(set(flat))


def _build_sentences(entities: dict) -> list[str]:
    """
    Extract individual sentences from project descriptions and experience
    bullets. Sentence-level comparison is more precise than corpus-level.
    """
    sentences = []

    for project in entities.get("projects", []):
        # Tech stack tokens — each one is its own "sentence"
        sentences.extend(project.get("tech_stack", []))
        # Description split into sentences
        desc = project.get("description", "")
        sentences.extend([s.strip() for s in re.split(r"[.!\n]", desc) if len(s.strip()) > 8])

    for exp in entities.get("experience", []):
        sentences.extend(exp.get("bullets", []))
        sentences.append(exp.get("title", ""))
        sentences.append(exp.get("company", ""))

    return [s for s in sentences if s]


def _exact_match(skill: str, sentences: list[str]) -> bool:
    corpus = " ".join(sentences)
    return bool(re.search(re.escape(skill), corpus, re.IGNORECASE))


# ── Core enrichment ───────────────────────────────────────────────────────────

SIMILARITY_THRESHOLD = 0.42


def enrich_skills(entities: dict) -> dict:
    # ── Pull coursework topics from education into skills ─────────────────────
    # If any education entry has a "coursework" field (populated by entity_extractor),
    # add those topics as a Coursework skill category.
    coursework_topics = []
    for edu in entities.get("education", []):
        for topic in edu.get("coursework", []):
            if topic.strip() and len(topic.strip()) > 2:
                coursework_topics.append(topic.strip())

    if coursework_topics:
        skills = entities.setdefault("skills", {})
        existing_flat = {s.lower() for items in skills.values() for s in items}
        new_topics = [t for t in coursework_topics if t.lower() not in existing_flat]
        if new_topics:
            skills["Coursework"] = new_topics

    model = _get_model()

    listed_skills = _flatten_listed_skills(entities.get("skills", {}))
    sentences     = _build_sentences(entities)

    if not sentences:
        entities["skill_analysis"] = {
            "all_listed":  listed_skills,
            "evidenced":   [],
            "listed_only": listed_skills,
            "implied":     [],
        }
        return entities

    # Embed all sentences once
    sentence_embeddings = model.encode(sentences, convert_to_tensor=True)

    # ── A: evidence scoring for listed skills ─────────────────────────────────
    evidenced   = []
    listed_only = []

    for skill in listed_skills:
        # Implicit whitelist — always evidenced
        if skill.lower() in IMPLICIT_EVIDENCE:
            evidenced.append(skill)
            continue

        # Exact string match
        if _exact_match(skill, sentences):
            evidenced.append(skill)
            continue

        # Semantic match: embed skill, find max similarity across sentences
        skill_emb = model.encode(skill, convert_to_tensor=True)
        sims      = util.cos_sim(skill_emb, sentence_embeddings)[0]
        max_sim   = float(sims.max())

        if max_sim >= SIMILARITY_THRESHOLD:
            evidenced.append(skill)
        else:
            listed_only.append(skill)

    # ── B: implied skill detection ────────────────────────────────────────────
    # For each taxonomy skill NOT listed, check if any sentence is highly
    # similar to it. Sentence-level avoids corpus dilution.

    listed_lower    = {s.lower() for s in listed_skills}
    taxonomy_skills = [s for s in SKILLS_TAXONOMY if s.lower() not in listed_lower]
    taxonomy_embs   = model.encode(taxonomy_skills, convert_to_tensor=True)

    # Max similarity across all sentences for each taxonomy skill
    all_sims = util.cos_sim(sentence_embeddings, taxonomy_embs)  # [n_sentences x n_taxonomy]
    max_sims = all_sims.max(dim=0).values                         # [n_taxonomy]

    implied_scored = [
        (taxonomy_skills[i], float(max_sims[i]))
        for i in range(len(taxonomy_skills))
        if float(max_sims[i]) >= SIMILARITY_THRESHOLD
    ]
    implied_scored.sort(key=lambda x: x[1], reverse=True)
    implied = [s for s, _ in implied_scored[:15]]

    entities["skill_analysis"] = {
        "all_listed":  listed_skills,
        "evidenced":   sorted(evidenced),
        "listed_only": sorted(listed_only),
        "implied":     implied,
    }

    return entities


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    from extractor import extract_pdf
    from segmenter import segment
    from entity_extractor import extract_entities

    extracted = extract_pdf("synthetic_resume.pdf")
    sections  = segment(extracted)
    entities  = extract_entities(sections)
    enriched  = enrich_skills(entities)

    sa = enriched["skill_analysis"]

    print(f"Listed skills  : {len(sa['all_listed'])}")
    print(f"Evidenced      : {len(sa['evidenced'])}")
    print(f"Listed only    : {len(sa['listed_only'])}")
    print(f"Implied (top)  : {len(sa['implied'])}")
    print()
    print("EVIDENCED:")
    for s in sa["evidenced"]:
        print(f"  ✓  {s}")
    print()
    print("LISTED ONLY (no project evidence):")
    for s in sa["listed_only"]:
        print(f"  ⚠  {s}")
    print()
    print("IMPLIED (in project text, not listed):")
    for s in sa["implied"]:
        print(f"  →  {s}")
