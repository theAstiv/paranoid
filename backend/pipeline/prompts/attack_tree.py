"""Attack tree generation prompts for visual threat analysis.

This module provides prompts for generating Mermaid.js attack tree diagrams
that show how a threat could be realised, so defenders can place controls and
detections.

The prompt is deliberately framed as defensive analysis at tactic level: the
earlier attacker-side wording (per-phase technique lists, "sophisticated
techniques") was refused by Bedrock's content filter on Opus 5.5 and Fable 5.1
for 24/36 and 36/37 threats (BB-55), including purely defensive findings.
"""


def attack_tree_prompt() -> str:
    """Generate prompt for attack tree creation in Mermaid.js format."""
    return """
<task>
You are helping a security team model how a threat could be realised, so they can place controls and detections. Your goal is to create an attack tree diagram for a given security threat using Mermaid.js graph syntax. The tree should show the preconditions and alternative paths that lead to the threat's outcome, so defenders can see which steps to prevent or detect.
</task>

<instructions>

1. Review the threat information:

   * <threat_name>: The name of the threat
   * <threat_description>: Detailed description of the threat
   * <target>: The target asset or component
   * <stride_category> or <maestro_category>: The threat classification
   * <mitigations>: Existing mitigations (to help identify which steps they block)

2. Attack Tree Structure Guidelines:

   **Root Node (Goal):**
   - The root should represent the threat's outcome
   - Format: Clear, action-oriented statement
   - Example: "Unauthorized Access to Database"

   **AND/OR Logic:**
   - **AND nodes** (◆): All child nodes must be achieved
   - **OR nodes** (○): Any one child node is sufficient
   - Use AND for sequential requirements
   - Use OR for alternative paths

   **Leaf Nodes (Steps and Preconditions):**
   - Tactic-level steps or preconditions a defender can act on
   - Based on realistic scenarios for this system
   - Map to MITRE ATT&CK tactics where applicable

   **Labelling rule:**
   - Label nodes at the level of tactics and preconditions, for example
     "Obtain valid credentials" or "Escalate privileges".
   - Do not include commands, payloads, exploit code or step-by-step instructions.

3. Mermaid.js Graph Syntax:

   Use the following Mermaid flowchart syntax:

   ```
   graph TD
       Root[Threat Outcome]
       AND1{{AND}}
       OR1{OR}
       Step1[Step 1]
       Step2[Step 2]

       Root --> AND1
       AND1 --> Step1
       AND1 --> OR1
       OR1 --> Step2a[Alternative Step 2a]
       OR1 --> Step2b[Alternative Step 2b]
   ```

   **Node Shapes:**
   - `[Text]` - Rectangular box for steps
   - `{{Text}}` - Diamond for AND gates
   - `{Text}` - Rhombus for OR gates
   - `([Text])` - Stadium shape for entry points
   - `[(Text)]` - Cylinder for data/resources

4. Attack Tree Best Practices:

   **Depth:**
   - 3-5 levels deep for most threats
   - Top level: Strategic goal
   - Middle levels: Tactical approaches
   - Leaf nodes: Tactics and preconditions

   **Breadth:**
   - Show 2-4 alternative paths (OR branches)
   - Include common paths into the target
   - Consider different levels of attacker access

   **Completeness:**
   - Cover the main path from the threat description
   - Include prerequisites (access, knowledge)
   - Show privilege escalation if relevant
   - Include the resulting impact

5. Tactic Categories (use these as node labels, not as technique detail):

   - Initial access: obtain valid credentials, compromise a dependency, reach an exposed interface
   - Execution: run unauthorized code or logic in the target
   - Persistence: retain access across restarts or credential changes
   - Privilege escalation: gain broader permissions than intended
   - Defense evasion: avoid detection or logging
   - Credential access: obtain secrets, tokens or keys
   - Discovery: learn about the environment or the model
   - Lateral movement: move between components or tenants
   - Collection and exfiltration: gather and remove data
   - Impact: data loss, service disruption, corrupted outputs

6. ML/AI-Specific Paths (if MAESTRO category):

   - Model abuse: repeated access to the model API lets an outsider approximate its behaviour
   - Training pipeline: tampering with data or artifacts before they reach the model
   - Privacy: model outputs that reveal information about training data
   - Supply chain: an untrusted model or dependency enters the pipeline

7. Output Format:

   Provide ONLY the Mermaid.js graph code. Do not include markdown code fences.
   Start directly with `graph TD` or `graph LR`.

   **Example structure:**

   graph TD
       Goal[Threat Outcome]
       AND1{{AND: Prerequisites}}
       OR1{OR: Entry Paths}

       Goal --> AND1
       AND1 --> Initial([Initial Access])
       AND1 --> Escalate[Escalate Privileges]

       Initial --> OR1
       OR1 --> Phish[Social Engineering]
       OR1 --> Exploit[Unpatched Vulnerability]
       OR1 --> Creds[Obtain Valid Credentials]

       Escalate --> AND2{{AND: Escalation Steps}}
       AND2 --> FindVuln[Find Misconfiguration]
       AND2 --> UseVuln[Gain Broader Permissions]

       UseVuln --> Impact[Achieve Impact]
       Impact --> Exfil[(Data Exposure)]

8. Quality Control Checklist:

   * [ ] Does the tree clearly show how the threat is realised?
   * [ ] Are AND/OR gates used correctly?
   * [ ] Are all paths realistic for this system?
   * [ ] Does the tree depth match threat complexity?
   * [ ] Is the Mermaid syntax valid?
   * [ ] Are node labels clear, concise and tactic-level?
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

10. Special Considerations:

    **For Compound Threats:**
    - Show how multiple steps combine
    - Use AND gates to show required prerequisites

    **For Chains:**
    - Show progression from initial access to final impact
    - Include intermediate objectives

    **For ML/AI Threats:**
    - Include ML-specific nodes (model access, data pipeline, etc.)

Remember: the tree is for defenders. It should clearly show which steps must be prevented or detected to stop the threat.

</instructions>
"""
