from rest_framework.permissions import BasePermission


class IsCreator(BasePermission):
    """Allow access only to authenticated users with at least one published joke submission."""

    message = 'You must have at least one published joke to view creator insights.'

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u
            and u.is_authenticated
            and u.joke_submissions.filter(status='published').exists()
        )
