from bench.docs.files import Reference
from bench.docs.render import Document

REFERENCE = Reference(
    package="sample",
    header="<!-- generated -->\n",
    documents={
        "reference/models": Document("Models", "The sample's models.", ("models.Answer",), (("About", "models"),))
    },
)
