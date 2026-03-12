# Week 1 Notes

## Overall Architecture
The Azure Function receives cutting jobs via POST requests, 
validates them, and queues them in Service Bus. The Container 
Apps Job then picks up the job from the queue and runs cuOpt 
to solve the cutting stock problem.

## Key Decisions in PR
- Managed Identity used instead of connection strings, more 
secure as no passwords are stored anywhere in the code
- KEDA used for auto-scaling, container only runs when there 
are jobs in the queue, saving costs

## Areas Needing Clarification
- If multiple jobs come in at once, does KEDA spin up multiple 
containers or process them one by one?
- Will production data follow the same schema as example payload?
- Where does the cuOpt result go after solving?
- Is there a business limit on order quantities?
- Local testing without actual Azure Service Bus?

## Resources Used
- PR documentation
- getting-started.md
- infrastructure.md

