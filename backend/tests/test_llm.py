from app.services.llm_services import LLMService

if __name__ == "__main__":
    llm = LLMService()

    response = llm.generate_content(
        system_prompt="You are TestNova AI.",
        user_prompt="Say hello in one sentence."
    )

    print(response)