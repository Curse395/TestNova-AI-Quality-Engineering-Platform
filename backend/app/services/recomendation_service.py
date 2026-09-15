from sqlalchemy.orm import Session

class RecommendationService:

    def __init__(self,db:Session):
        self.db=db

    def get_workspace_recomendations(self,dashboard:dict):
        recommendations=[]

        coverage=dashboard["overview"]["overall_coverage"]
        confidence=dashboard["quality_center"]["release_confidence"]

        if coverage < 100:
            recommendations.append({"title":"Generate missing Embeddings",
                                   "description":"Some uploaded documents have not been embedded yet",
                                   "action":"generate_embeddings",
                                   "priority":"High"})

        if dashboard["live_health"]["needs_review"] > 0:
            recommendations.append({
                "title":"Review Project Health",
                "description":"Some projects require attention before release.",
                "action":"review_projects",
                "priority":"Medium"
            })

        if dashboard["live_health"]["critical"] > 0:
            recommendations.append({
                "title":"Resolve Critical Projects",
                "description":"Critical Projects should be fixed immediately.",
                "action":"fix_critical_projects",
                "priority":"High"
            })

        if confidence < 60:
             recommendations.append({
                  "title":"Improve Relases Readiness",
                  "description":"Release confidence is below the recommended threshold.",
                  "action":"improve_release",
                  "priority":"High"
             })

        if not recommendations:
             recommendations.append({
                  "title":"workspace is Healthy",
                  "description":"Everthing looks good. Consider generating AI-Powered test cases.",
                  "action":"generate_tests",
                  "priority":"Low"
             })
        return recommendations