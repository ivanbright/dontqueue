"""Small form helpers shared across apps."""

from django import forms


def style_fields(form, css_class="input"):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            continue
        existing = field.widget.attrs.get("class", "")
        field.widget.attrs["class"] = f"{existing} {css_class}".strip()
    return form
