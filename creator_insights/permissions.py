from rest_framework.permissions import BasePermission


class IsCreator(BasePermission):
    """Allow authors with currently published content, including direct attribution."""

    message = 'You must have at least one published joke to view creator insights.'

    def has_permission(self, request, view):
        from creator_insights.services import resolve_creator_jokes

        u = request.user
        return bool(
            u
            and u.is_authenticated
            and resolve_creator_jokes(u).exists()
        )
