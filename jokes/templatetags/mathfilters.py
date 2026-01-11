from django import template

register = template.Library()


@register.filter
def multiply(value, arg):
    """Multiply value by arg."""
    try:
        return int(value) * int(arg)
    except (ValueError, TypeError):
        return ''
