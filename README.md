# Telemetry Guidance
This repo contains documentation for many common telemetry questions and useful queries, along with explanations of how each of the queries work

## Types of Telemetry
There are 3 main sources of telemetry:
- **Internal Microsoft Telemetry:** Telemetry from Microsoft employees. Can be shared on Teams, via email, etc, and used to train models
- **GitHub Telemetry:** Telemetry from external individual users. Data from the restricted tables cannot be shared via any means and must be deleted every month.
- **VS Code Extension Telemetry:** Anonymized telemetry across all users. Does not contain any code, queries or model responses.

## Agentic Conversation Data Structures
Conversations with the VS Code Agent are broken down in telemetry via 2 types of IDs: `conversation_id` and `message_id` (although, depending on the table, `message_id` may be referenced as `headerRequestId` or `requestId` instead). To explain how conversations are structured in telemetry, consider the following example:


<img width="522" height="579" alt="Screenshot 2025-11-05 at 9 00 00 AM" src="https://github.com/user-attachments/assets/d32c0a65-c670-48af-ad01-9a0094f041ad" />

- `conversation_id` represents the full conversation window. Each time you press the "+" in the top right corner of the VS Code chat window, you start a new conversation and create a new conversation id. Every portion of the example above will have the same conversation id.
- `message_id` represents one user message (or a "User Turn", as we call it) and the subsequent model actions (or "Model Turns") pertaining to that message. Consider offline benchmarks: each test case would have one single `message_id` (because there is no new user query during the model's action taking).

So, one `conversation_id` consists of many `message_id`s.

There are 2 main data structures for agentic conversations: Conversation Messages and Conversation Trajectories. 
### Conversation Messages
The conversation messages consist of messages back and forth between the user and the model. They are the text visible in the copilot chat window -- none of the tool calls, system messages, etc. Just the text between the user and the model. In the above example, the conversation messages would be:
```
(conversation_id 1)
(message_id 1) USER: "hello"
(message_id 1) MODEL: "Hello! I can see you're working on the searchSubagentTool.ts file in the GitHub Copilot Chat extension. How can I help you today?"
(message_id 2) USER: "tell me what I'm working on"
(message_id 2) MODEL: "I'll examine the current file and your recent changes to understand what you're working on."
(message_id 2) MODEL: "You're working on implementing a new search subagent tool for the GitHub Copilot Chat extension. Here's what you've done on the anisha/search_subagent branch:"
```
I have also labeled which turns are associated with which message id. Here, you can see that **there are often many model events associated with the same message id.**

#### Data Quirks
There is **a lot** of duplication in this data. That is because, every time the model takes a new step (i.e. calling a tool), its last message and the last user message is re-sent to telemetry. Queries to get a clean picture of this data should be post-processed with code such as:

```python
  conversation_parts = []
  previous_contents = set({})
  
  for turn in extracted_turns:
      current_content = turn['message_text']
      
      # Skip if this is a model turn with the same content as previous turns
      
      if turn['source'] == 'user':
          conversation_parts.append(f"****USER****: {current_content}")
      else:  # model
          if current_content in previous_contents:
              continue
          else:
              previous_contents.add(current_content)

          conversation_parts.append(f"****MODEL****: {current_content}")

```

### Conversation Trajectories
The conversation trajectories are the full message JSON sent back and forth to the LLM API. It contains all the information the model would have access to, including: previous tool call results, conversation messages, system prompts, etc. This data tends to be very large and more cumbersome, but also more rich. 


## Internal Telemetry
Relevant Table: AppEvents
Data Structure: most relevant fields will be under `properties` or `measurements`
Example query & link to query:

Link to query [here:](https://dataexplorer.azure.com/clusters/https%3A%2F%2Fade.loganalytics.io%2Fsubscriptions%2Fd0c05057-7972-46ff-9bcf-3c932250155e%2FresourceGroups%2FCopilotChatEval%2Fproviders%2FMicrosoft.OperationalInsights%2Fworkspaces%2Fd0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2/databases/d0c05057-7972-46ff-9bcf-3c932250155e-CopilotChatEval-EUS2?query=H4sIAAAAAAAAA1WOMQvCMBSEd3%2FFo1OFItJdwUFEB3HoXp7JUdPaJOSl1cEfbwqidXrf4%2B6423m%2FH2GjLF70uCGAKtPjAIvAEZq2xI3LS7386mfuQcrZyMYKZYlGBOFonF31EOEGFZ4xS4F0YDVdgvMI0UBO4ixtyHMQ1G168p82NWDk%2B5B66cpNPVjPqsv%2F05Mrcgcq14l8cC1UJHFDUChoPuaoC%2FrsmeE07Q37LSXb9AAAAA%3D%3D)
```KQL
AppEvents
| where TimeGenerated > ago(2d)
| where Name contains "conversation.messageText"
| extend PropertiesJson = parse_json(Properties)
| evaluate bag_unpack(PropertiesJson)
| take 20
| project source, conversationId, messageId, messageText
```

## GitHub Telemetry
- Relevant Tables: `copilot_v0_restricted_copilot_event`, `copilot_v0_copilot_event`, `copilot_v0_restricted_copilot_code_snippet`
- Common relevant event names: `toolCallDetailsExternal`, `engine.messages`, `conversation.messageText`, `panel.edit.feedback`


## VS Code Extension Telemetry

## Relevant Scripts
- `export_kusto.py`: python script to download data given a kusto query. This is necessary because "Export to CSV" in the Azure Data Exporer will truncate heavily. Alter the file to have the correct column names given your kusto query. Run with a command such as `python export_kusto.py kusto_scripts/gh_messages`
- `kusto_scripts/`: KQL (Kusto Query Language) scripts that can be used to collect common desired telemetry. 


