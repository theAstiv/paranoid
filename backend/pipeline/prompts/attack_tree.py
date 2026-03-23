"""Attack tree generation prompts for visual threat analysis.

This module provides prompts for generating Mermaid.js attack tree diagrams
that visualize attack paths and threat scenarios.
"""


def attack_tree_prompt() -> str:
    """Generate prompt for attack tree creation in Mermaid.js format."""
    return """
<task>
You are an expert in cybersecurity and attack path analysis. Your goal is to create a detailed attack tree diagram for a given security threat using Mermaid.js graph syntax. The attack tree should visualize how an attacker could achieve the threat's objective, breaking it down into logical steps and alternative paths.
</task>

<instructions>

1. Review the threat information:

   * <threat_name>: The name of the threat
   * <threat_description>: Detailed description of the threat
   * <target>: The target asset or component
   * <stride_category> or <maestro_category>: The threat classification
   * <mitigations>: Existing mitigations (to help identify attack steps)

2. Attack Tree Structure Guidelines:

   **Root Node (Goal):**
   - The root should represent the attacker's ultimate objective
   - Format: Clear, action-oriented statement
   - Example: "Gain Unauthorized Access to Database"

   **AND/OR Logic:**
   - **AND nodes** (◆): All child nodes must be achieved
   - **OR nodes** (○): Any one child node is sufficient
   - Use AND for sequential requirements
   - Use OR for alternative attack paths

   **Leaf Nodes (Attack Steps):**
   - Specific, actionable attack techniques
   - Based on realistic attack methodologies
   - Map to MITRE ATT&CK techniques where applicable

3. Mermaid.js Graph Syntax:

   Use the following Mermaid flowchart syntax:

   ```
   graph TD
       Root[Attacker Goal]
       AND1{{AND}}
       OR1{OR}
       Step1[Attack Step 1]
       Step2[Attack Step 2]

       Root --> AND1
       AND1 --> Step1
       AND1 --> OR1
       OR1 --> Step2a[Alternative Step 2a]
       OR1 --> Step2b[Alternative Step 2b]
   ```

   **Node Shapes:**
   - `[Text]` - Rectangular box for attack steps
   - `{{Text}}` - Diamond for AND gates
   - `{Text}` - Rhombus for OR gates
   - `([Text])` - Stadium shape for entry points
   - `[(Text)]` - Cylinder for data/resources

4. Attack Tree Best Practices:

   **Depth:**
   - 3-5 levels deep for most threats
   - Top level: Strategic goal
   - Middle levels: Tactical approaches
   - Leaf nodes: Technical techniques

   **Breadth:**
   - Show 2-4 alternative paths (OR branches)
   - Include common attack vectors
   - Consider different attacker skill levels

   **Completeness:**
   - Cover the main attack path from threat description
   - Include prerequisite steps (reconnaissance, access)
   - Show privilege escalation if relevant
   - Include data exfiltration or impact steps

5. Attack Phase Categories:

   **Initial Access:**
   - Phishing, credential theft, vulnerability exploitation
   - Supply chain compromise, physical access

   **Execution:**
   - Code execution, script running, command injection
   - Exploiting application logic

   **Persistence:**
   - Backdoors, account creation, scheduled tasks
   - Model backdoors (for ML threats)

   **Privilege Escalation:**
   - Exploiting misconfigurations, elevation attacks
   - Token manipulation, sudo abuse

   **Defense Evasion:**
   - Obfuscation, anti-forensics, disabling security tools
   - Adversarial perturbations (for ML threats)

   **Credential Access:**
   - Credential dumping, brute force, password spraying
   - API key extraction

   **Discovery:**
   - Network scanning, file enumeration, API exploration
   - Model probing, feature extraction

   **Lateral Movement:**
   - Pass-the-hash, remote services, internal phishing
   - Model-to-model attacks

   **Collection:**
   - Data scraping, screenshot capture, clipboard theft
   - Training data extraction, model weights theft

   **Exfiltration:**
   - Data transfer, C2 channels, physical removal
   - Model extraction via API queries

   **Impact:**
   - Data destruction, DoS, ransomware, defacement
   - Model poisoning, prediction manipulation

6. ML/AI-Specific Attack Paths (if MAESTRO category):

   **For ML Model Attacks:**
   - Query API → Collect outputs → Train surrogate model → Extract functionality
   - Access training pipeline → Inject poisoned samples → Trigger backdoor
   - Craft adversarial inputs → Test perturbations → Deploy evasion attack

   **For Privacy Attacks:**
   - Query model repeatedly → Analyze confidence scores → Infer training membership
   - Submit targeted queries → Reconstruct sensitive attributes → Extract PII

   **For Supply Chain Attacks:**
   - Compromise model repository → Upload backdoored model → Wait for download → Activate trigger

7. Output Format:

   Provide ONLY the Mermaid.js graph code. Do not include markdown code fences.
   Start directly with `graph TD` or `graph LR`.

   **Example structure:**

   graph TD
       Goal[Achieve Threat Objective]
       AND1{{AND: Prerequisites}}
       OR1{OR: Attack Vectors}

       Goal --> AND1
       AND1 --> Initial([Initial Access])
       AND1 --> Escalate[Escalate Privileges]

       Initial --> OR1
       OR1 --> Phish[Phishing Attack]
       OR1 --> Exploit[Exploit Vulnerability]
       OR1 --> Creds[Stolen Credentials]

       Escalate --> AND2{{AND: Escalation Steps}}
       AND2 --> FindVuln[Identify Misconfiguration]
       AND2 --> ExecuteExploit[Execute Privilege Escalation]

       ExecuteExploit --> Impact[Achieve Impact]
       Impact --> Exfil[(Data Exfiltration)]

8. Quality Control Checklist:

   * [ ] Does the tree clearly show how the threat is realized?
   * [ ] Are AND/OR gates used correctly?
   * [ ] Are all paths realistic and technically feasible?
   * [ ] Does the tree depth match threat complexity?
   * [ ] Is the Mermaid syntax valid?
   * [ ] Are node labels clear and concise?
   * [ ] Does the tree align with the threat description?
   * [ ] Are mitigations implicitly addressed (show what they block)?

9. Scope and Complexity Guidance:

   **For Low/Medium Threats:**
   - 2-3 levels deep
   - 1-2 alternative paths
   - 6-10 total nodes

   **For High/Critical Threats:**
   - 3-5 levels deep
   - 2-4 alternative paths
   - 12-20 total nodes
   - Include sophisticated techniques

10. Special Considerations:

    **For Compound Threats:**
    - Show how multiple sub-attacks combine
    - Use AND gates to show required prerequisites

    **For Attack Chains:**
    - Show progression from initial access to final impact
    - Include intermediate objectives

    **For ML/AI Threats:**
    - Include ML-specific nodes (model querying, gradient analysis, etc.)
    - Show iterative attack refinement where applicable

Remember: The attack tree should be actionable intelligence for defenders. It should clearly show what attack steps must be prevented or detected to stop the threat.

</instructions>
"""
