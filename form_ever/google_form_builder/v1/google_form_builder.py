from autom.logger import autom_logger
from autom.utils import SingleLLMUsage
from autom.engine.integration_auth import google_forms_auth_meta
from autom.engine.integration_auth import IntegrationAuthRequirement
from autom.official import BaseOpenAIWorker, IdentityBridgeWorker, HolderAgentWorker
from autom.engine import GraphAgentWorker, AutomGraph, Node, Link, AutomSchema, AgentWorker, Request, Response, autom_registry

from .prompt import questionaire_desginer_system_prompt, questionaire_designer_user_input_prompt
from .schema import QuestionaireDesignRequirement, QuestionaireDesign, GoogleFormsCreateFormResponse


@autom_registry(is_internal=False)
class QuestionaireDesigner(BaseOpenAIWorker, AgentWorker):
    """Questionaire Designer. Produce high-quality and detailed design of a questionaire based on user's requirement.

    The output design can be exportted into different formats, such as Google Forms, Microsoft Forms, etc.
    """
    @classmethod
    def define_name(cls) -> str:
        return "Questionaire Designer"

    @classmethod
    def define_input_schema(cls) -> AutomSchema | None:
        return QuestionaireDesignRequirement

    @classmethod
    def define_output_schema(cls) -> AutomSchema | None:
        return QuestionaireDesign

    def invoke(self, req: Request) -> Response:
        req_body: QuestionaireDesignRequirement = req.body

        resp = Response[QuestionaireDesign].from_worker(self)
        chat_completion = self.openai_client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": questionaire_desginer_system_prompt.format()},
                    {"role": "user", "content": questionaire_designer_user_input_prompt.format(
                        user_requirement=req_body.user_requirement,
                    )},
                ],
                response_format=QuestionaireDesign,
            )
        resp.add_llm_usage(SingleLLMUsage.from_openai_chat_completion(chat_completion))
        resp.body = chat_completion.choices[0].message.parsed
        if resp.body is None:
            raise RuntimeError(f"Failed to parse the response from OpenAI chat completion: {chat_completion}")
        try:
            resp_body: QuestionaireDesign = resp.body
            autom_logger.info(f"[GoogleFormBuilder] Form Design accomeplished! Pushing to Google Forms...")
            form_create_response = resp_body.create_google_form(
                access_token=self.integration_auth_manager.get(
                    integration_qualifier='google_forms',
                    secret_qualifier='api_key',
                    required=True,
                )
            )
            autom_logger.info(f"[GoogleFormBuilder] Form created successfully! Response Url: {form_create_response.respond_url}, or edit it at {form_create_response.edit_url}")
        except Exception as e:
            autom_logger.error(f"[GoogleFormBuilder] Failed to push the form to Google Forms: {e}")
            raise e

        return resp.success()


@autom_registry(is_internal=False)
class GoogleFormCreator(AgentWorker):
    """Execution Agent to turn a questionaire design into a real Google Form."""
    @classmethod
    def define_name(cls) -> str:
        return "Google Form Creator"

    @classmethod
    def define_input_schema(cls) -> AutomSchema | None:
        return QuestionaireDesign

    @classmethod
    def define_output_schema(cls) -> AutomSchema | None:
        return GoogleFormsCreateFormResponse

    @classmethod
    def define_integration_auth_requirement(cls) -> IntegrationAuthRequirement:
        return IntegrationAuthRequirement().require(
            google_forms_auth_meta, optional=False,
        )

    def invoke(self, req: Request) -> Response:
        req_body: QuestionaireDesign = req.body
        gforms_access_token = self.integration_auth_manager.get(
            integration_qualifier='google_forms',
            secret_qualifier='api_key',
            required=True
        )
        google_forms_create_response = req_body.create_google_form(access_token=gforms_access_token)
        return Response[GoogleFormsCreateFormResponse].from_worker(self).success(
            body=google_forms_create_response
        )


@autom_registry(is_internal=False)
class GoogleFormBuilder(GraphAgentWorker):
    """The REAL intelligent assistant who helps you create a Google Form from scratch.
    
    Whatever you want to investigate, survey, or collect data, just input your requirement and let the assistant do the rest.
    """
    @classmethod
    def define_name(cls) -> str:
        return "Google Form Builder"

    @classmethod
    def define_graph(cls) -> AutomGraph:
        graph = AutomGraph()

        entry_node = Node.from_worker(HolderAgentWorker().with_schema(QuestionaireDesignRequirement))
        entry_questionaire_designer_bridge = Link.from_worker(IdentityBridgeWorker())
        questionaire_designer = Node.from_worker(QuestionaireDesigner())
        questionaire_designer_google_form_creator_bridge = Link.from_worker(IdentityBridgeWorker())
        google_form_creator = Node.from_worker(GoogleFormCreator())

        graph.add_node(entry_node)
        graph.add_node(questionaire_designer)
        graph.add_node(google_form_creator)

        graph.bridge(entry_node, questionaire_designer, entry_questionaire_designer_bridge)
        graph.bridge(questionaire_designer, google_form_creator, questionaire_designer_google_form_creator_bridge)

        graph.set_entry_node(entry_node)
        graph.set_exit_node(google_form_creator)

        return graph


__all__ = [
    'QuestionaireDesigner',
    'GoogleFormCreator',
    'GoogleFormBuilder',
]
