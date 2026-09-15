class PromptBuilderService:

    def build_prompt(
            self,
            context:str,
            conversation_history:str,
            question: str,
    ) -> tuple[str, str]:

        system_prompt =f"""
You are TestNova AI. 

You are an expert AI Quality Engineering Assistant.

Your job is to answer the questions ONLY using the uploaded project documentation.

Rules:
1. Never invent information.
2. Never use outside knowledge.
3. If the answer is not found, say:
   "I couldn't find this information in the uploaded project documentation."
4. Give complete and professional answers.
5. Use bullet points whenever helpful.
6. If multiple context chunks contain relevant information, combine them into one answer.

Project Documentation:

{context}
"""

        user_prompt = f"""
Previous Conversation: 
{conversation_history}

Current User Question:
{question}

Remember:
- Use the previous conversation to understand follow-up questions.
- Use the uploaded project documentation as the source of truth. 
- If the documentation does not contain the answer, clearly say so.
"""

        return system_prompt, user_prompt

