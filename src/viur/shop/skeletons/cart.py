import logging

from viur.core import conf, db
from viur.core.bones import *
from viur.core.prototypes.tree import TreeSkel
from viur.core.skeleton import SkeletonInstance
from viur.shop.constants import *

logger = logging.getLogger("viur.shop").getChild(__name__)


def get_total_for_node(skel: "CartNodeSkel", bone: NumericBone) -> float:
    children = conf.main_app.shop.cart.get_children(skel["key"])
    total = 0
    for child in children:
        if issubclass(child.skeletonCls, CartNodeSkel):
            total += child["total"]
        elif issubclass(child.skeletonCls, CartItemSkel):
            total += child["shop_price_retail"] * child["quantity"]
    # TODO: discount logic
    return round(total, bone.precision)


class CartNodeSkel(TreeSkel):  # STATE: Complete (as in model)
    kindName = "shop_cart_node"

    is_root_node = BooleanBone(
        descr="Is root node?",
        readOnly=True,
    )

    total = NumericBone(
        descr="Total",
        precision=2,
        compute=Compute(get_total_for_node, ComputeInterval(ComputeMethod.Always)),
        # compute=Compute(get_total_for_node, ComputeInterval(ComputeMethod.OnWrite)),
    )

    vat_total = NumericBone(
        descr="Total",
        precision=2,
        # TODO: compute=Compute(get_total_vat_for_node, ComputeInterval(ComputeMethod.Always)),
    )

    vat_rate = RelationalBone(
        descr="Vat Rate",
        kind="shop_vat",
        # TODO: compute=Compute(get_total_vat_rate_for_node, ComputeInterval(ComputeMethod.Always)),
    )

    # TODO(discussion): Add bone total_quantity ?

    shipping_address = RelationalBone(
        descr="shipping_address",
        kind="shop_address",
    )

    customer_comment = TextBone(
        descr="customer_comment",
        validHtml=None,
    )

    name = StringBone(
        descr="name",
    )

    cart_type = SelectBone(
        descr="cart_type",
        values=CartType,
    )

    shipping = RelationalBone(
        descr="shipping",
        kind="shop_shipping",
    )
    """Versand bei Warenkorb der einer Bestellung zugehört"""

    discount = RelationalBone(
        descr="discount",
        kind="shop_discount",
    )


class CartItemSkel(TreeSkel):  # STATE: Complete (as in model)
    kindName = "shop_cart_leaf"

    article = RelationalBone(
        descr="article",
        kind="...",  # will be set in Shop._set_kind_names()
        # FIXME: What's necessary here?
        parentKeys=["key", "parententry", "article"],
        refKeys=[
            "shop_name", "shop_description",
            "shop_price_retail", "shop_price_recommended",
            "shop_availability", "shop_listed",
            "shop_image", "shop_art_no_or_gtin",
            "shop_vat", "shop_shipping",
            "shop_is_weee", "shop_is_low_price",
        ],
    )

    # TODO(discussion): was not in the ER diagram; or did we want to create a new LeafSkel for each quantity?
    quantity = NumericBone(
        descr="quantity",
        min=0,
    )

    project_data = JsonBone(
        descr="Custom project data",
    )

    # --- Bones to store a frozen copy of the article values: -----------------

    shop_name = StringBone(
        descr="shop_name",
    )

    shop_description = TextBone(
        descr="shop_description",
    )

    shop_price_retail = NumericBone(
        descr="Verkaufspreis",
    )

    shop_price_recommended = NumericBone(
        descr="UVP",
    )

    shop_availability = SelectBone(
        descr="shop_availability",
        values=ArticleAvailability,
    )

    shop_listed = BooleanBone(
        descr="shop_listed",
    )

    shop_image = FileBone(
        descr="Produktbild",
    )

    shop_art_no_or_gtin = StringBone(
        descr="Artikelnummer",
    )

    shop_vat = RelationalBone(
        descr="Steuersatz",
        kind="shop_vat",
    )

    shop_shipping = RelationalBone(
        descr="Versandkosten",
        kind="shop_shipping",
    )

    shop_is_weee = BooleanBone(
        descr="Elektro",
    )

    shop_is_low_price = BooleanBone(
        descr="shop_is_low_price",
    )

    @classmethod
    def toDB(cls, skelValues: SkeletonInstance, update_relations: bool = True, **kwargs) -> db.Key:
        return super().toDB(skelValues, update_relations, **kwargs)
