import typing as t  # noqa

from viur.core import db
from viur.core.bones import *
from viur.core.prototypes.tree import TreeSkel
from viur.core.skeleton import SkeletonInstance
from viur.shop.types import *
from ..globals import SHOP_INSTANCE, SHOP_LOGGER
from ..types.response import make_json_dumpable

logger = SHOP_LOGGER.getChild(__name__)


class TotalFactory:
    def __init__(
        self,
        bone_node: str | t.Callable[[SkeletonInstance], float | int],
        bone_leaf: str | t.Callable[[SkeletonInstance], float | int],
        multiply_quantity: bool = True,
        precision: int | None = None,
        use_cache: bool = True,
    ):
        super().__init__()
        self.bone_node = bone_node
        self.bone_leaf = bone_leaf
        self.multiply_quantity = multiply_quantity
        self.precision = precision
        self.use_cache = use_cache

    def _get_children(self, parent_cart_key: db.Key) -> list[SkeletonInstance]:
        if self.use_cache:
            return SHOP_INSTANCE.get().cart.get_children_from_cache(parent_cart_key)
        else:
            return SHOP_INSTANCE.get().cart.get_children(parent_cart_key)

    def __call__(self, skel: "CartNodeSkel", bone: NumericBone):
        children = self._get_children(skel["key"])
        total = 0
        for child in children:
            # logger.debug(f"{child = }")
            if issubclass(child.skeletonCls, CartNodeSkel):
                if callable(self.bone_node):
                    total += self.bone_node(child)
                else:
                    total += child[self.bone_node]
            elif issubclass(child.skeletonCls, CartItemSkel):
                if callable(self.bone_leaf):
                    value = self.bone_leaf(child)
                else:
                    value = child[self.bone_leaf]
                if value:
                    if self.multiply_quantity:
                        value *= child["quantity"]
                    total += value

        return round(
            total,
            self.precision if self.precision is not None else bone.precision
        )


class DiscountFactory(TotalFactory):
    def __call__(self, skel: "CartNodeSkel", bone: NumericBone):
        total = super().__call__(skel, bone)
        if discount := skel["discount"]:
            if any(
                condition["dest"]["application_domain"] == ApplicationDomain.BASKET
                for condition in discount["dest"]["condition"]
            ):
                total = Price.apply_discount(discount["dest"], total)
        return round(
            total,
            self.precision if self.precision is not None else bone.precision
        )


def get_vat_rate_for_node(skel: "CartNodeSkel", bone: RelationalBone):
    children = SHOP_INSTANCE.get().cart.get_children_from_cache(skel["key"])
    rel_keys = set()
    # logger.debug(f"{skel = }")
    for child in children:
        # logger.debug(f"{child = }")
        if issubclass(child.skeletonCls, CartNodeSkel):
            for rel in child["vat_rate"] or []:
                if rel is None:
                    logger.error(f'Relation vat_rate of {child["key"]} is broken.')
                    continue
                rel_keys.add(rel["dest"]["key"])
        elif issubclass(child.skeletonCls, CartItemSkel):
            if child["shop_vat"] is not None:
                rel_keys.add(child["shop_vat"]["dest"]["key"])
    return [
        bone.createRelSkelFromKey(key)
        for key in rel_keys
    ]


class CartNodeSkel(TreeSkel):  # STATE: Complete (as in model)
    kindName = "{{viur_shop_modulename}}_cart_node"

    subSkels = {
        "discount": ["key", "discount", "parententry"],  # for modules.cart.get_discount_for_leaf
    }

    is_root_node = BooleanBone(
        readOnly=True,
    )

    total = NumericBone(
        precision=2,
        compute=Compute(
            TotalFactory("total", lambda child: child.price_.current, True),
            ComputeInterval(ComputeMethod.Always),
        ),
    )

    total_discount_price = NumericBone(
        precision=2,
        compute=Compute(
            DiscountFactory("total_discount_price", lambda child: child.price_.current, True),
            ComputeInterval(ComputeMethod.Always),
        ),
    )

    vat_total = NumericBone(
        precision=2,
        compute=Compute(
            TotalFactory("vat_total", lambda child: child.price_.vat_value, True),
            ComputeInterval(ComputeMethod.Always),
        ),
    )

    vat_rate = RelationalBone(
        kind="{{viur_shop_modulename}}_vat",
        module="{{viur_shop_modulename}}/vat",
        compute=Compute(get_vat_rate_for_node, ComputeInterval(ComputeMethod.Always)),
        refKeys=["key", "name", "rate"],
        multiple=True,
    )

    total_quantity = NumericBone(
        precision=0,
        compute=Compute(
            TotalFactory("total_quantity", lambda child: 1, True),
            ComputeInterval(ComputeMethod.Always)
        ),
        defaultValue=0,
    )

    shipping_address = RelationalBone(
        kind="{{viur_shop_modulename}}_address",
        module="{{viur_shop_modulename}}/shop_address",
        refKeys=[
            "key", "name", "customer_type", "salutation", "company_name",
            "firstname", "lastname", "street_name", "street_number",
            "address_addition", "zip_code", "city", "country",
            "is_default", "address_type",
        ],
    )

    customer_comment = TextBone(
        validHtml=None,
    )

    name = StringBone(
    )

    cart_type = SelectBone(
        values=CartType,
        translation_key_prefix=None,
    )

    shipping = RelationalBone(
        kind="{{viur_shop_modulename}}_shipping",
        module="{{viur_shop_modulename}}/shipping",
        refKeys=[
            "shipping_cost"
        ]
    )
    shipping_status = SelectBone(
        values=ShippingStatus,
        defaultValue=ShippingStatus.CHEAPEST
    )
    """Versand bei Warenkorb der einer Bestellung zugehört"""

    discount = RelationalBone(
        kind="{{viur_shop_modulename}}_discount",
        module="{{viur_shop_modulename}}/discount",
        refKeys=[
            "key",
            "name",
            "discount_type",
            "absolute",
            "percentage",
            "condition"
        ],
    )

    project_data = JsonBone(
    )


class CartItemSkel(TreeSkel):  # STATE: Complete (as in model)
    kindName = "{{viur_shop_modulename}}_cart_leaf"

    article = RelationalBone(
        kind="...",  # will be set in Shop._set_kind_names()
        module="...",  # will be set in Shop._set_kind_names()
        # FIXME: What's necessary here?
        parentKeys=["key", "parententry", "article"],
        refKeys=[
            "shop_name", "shop_description",
            "shop_price_retail", "shop_price_recommended",
            "shop_availability", "shop_listed",
            "shop_image", "shop_art_no_or_gtin",
            "shop_vat", "shop_shipping_config",
            "shop_is_weee", "shop_is_low_price",
            "shop_price_current",
        ],
        consistency=RelationalConsistency.CascadeDeletion,
    )

    quantity = NumericBone(
        min=0,
        defaultValue=0,
    )

    project_data = JsonBone(
    )

    # --- Bones to store a frozen copy of the article values: -----------------

    shop_name = StringBone(
    )

    shop_description = TextBone(
    )

    shop_price_retail = NumericBone(
    )

    shop_price_recommended = NumericBone(
    )

    shop_availability = SelectBone(
        values=ArticleAvailability,
        translation_key_prefix=None,
    )

    shop_listed = BooleanBone(
    )

    shop_image = FileBone(
    )

    shop_art_no_or_gtin = StringBone(
    )

    shop_vat = RelationalBone(
        kind="{{viur_shop_modulename}}_vat",
        module="{{viur_shop_modulename}}/vat",
        refKeys=["key", "name", "rate"],
        consistency=RelationalConsistency.PreventDeletion,
    )

    shop_shipping_config = RelationalBone(
        kind="{{viur_shop_modulename}}_shipping_config",
        module="{{viur_shop_modulename}}/shipping_config",
        consistency=RelationalConsistency.SetNull,
    )

    shop_is_weee = BooleanBone(
    )

    shop_is_low_price = BooleanBone(
    )

    @property
    def article_skel(self) -> SkeletonInstance:
        return self["article"]["dest"]

    @property
    def article_skel_full(self) -> SkeletonInstance:
        # TODO: Cache this property
        # logger.debug(f'Reading article_skel_full {self.article_skel["key"]=}')
        skel = SHOP_INSTANCE.get().article_skel()
        assert skel.fromDB(self.article_skel["key"])
        return skel

    @property
    def parent_skel(self) -> SkeletonInstance:
        if not (pk := self["parententry"]):
            return None
        skel = SHOP_INSTANCE.get().cart.viewSkel("node")
        assert skel.fromDB(pk)
        return skel

    @property
    def price_(self) -> Price:
        return Price.get_or_create(self)

    price = RawBone(  # FIXME: JsonBone doesn't work (https://github.com/viur-framework/viur-core/issues/1092)
        compute=Compute(lambda skel: skel.price_.to_dict(), ComputeInterval(ComputeMethod.Always))
    )
    price.type = JsonBone.type

    shipping = RawBone(  # FIXME: JsonBone doesn't work (https://github.com/viur-framework/viur-core/issues/1092)
        compute=Compute(
            lambda skel: make_json_dumpable(
                SHOP_INSTANCE.get().shipping.choose_shipping_skel_for_article(skel.article_skel_full)
            ),
            ComputeInterval(ComputeMethod.Always)),
    )
    shipping.type = JsonBone.type


    @classmethod
    def toDB(cls, skelValues: SkeletonInstance, update_relations: bool = True, **kwargs) -> db.Key:
        return super().toDB(skelValues, update_relations, **kwargs)
