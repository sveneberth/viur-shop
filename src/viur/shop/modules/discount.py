import io
import typing as t  # noqa

import cachetools

from viur.core import db, errors
from viur.core.prototypes import List
from viur.core.skeleton import SkeletonInstance
from viur.shop import DEBUG_DISCOUNTS
from viur.shop.types import *
from .abstract import ShopModuleAbstract
from ..globals import SHOP_LOGGER
from ..skeletons import DiscountSkel
from ..types.dc_scope import DiscountValidator

logger = SHOP_LOGGER.getChild(__name__)


class Discount(ShopModuleAbstract, List):
    moduleName = "discount"
    kindName = "{{viur_shop_modulename}}_discount"

    def adminInfo(self) -> dict:
        admin_info = super().adminInfo()
        admin_info["icon"] = "percent"
        admin_info["editViews"] = [
            {
                "module": "shop/discount_condition",
                "title": "Conditions",
                "context": "condition.dest.key",
                "filter": {
                    # "is_subcode": True,
                    # "orderby": "scope_code",
                },
                # "columns": ["scope_code", "quantity_used"],
            }
        ]
        return admin_info

    # --- Apply logic ---------------------------------------------------------

    def search(
        self,
        code: str | None = None,
        discount_key: db.Key | None = None,
    ) -> list[SkeletonInstance]:
        if not isinstance(code, (str, type(None))):
            raise TypeError(f"code must be an instance of str")
        if not isinstance(discount_key, (db.Key, type(None))):
            raise TypeError(f"discount_key must be an instance of db.Key")
        if not bool(code) ^ bool(discount_key):
            raise ValueError(f"Need code xor discount_code")

        skel = self.viewSkel()
        if discount_key is not None:
            if not skel.read(discount_key):
                raise errors.NotFound
            return [skel]
        elif code is not None:
            # Get condition skel(s) with this code
            cond_skels = list(self.shop.discount_condition.get_by_code(code))
            logger.debug(f"{code = } yields <{len(cond_skels)}>{cond_skels = }")
            if not cond_skels:
                raise errors.NotFound
            # Get discount skel(s) using these condition skel
            discount_skels = skel.all().filter("condition.dest.__key__ IN", [s["key"] for s in cond_skels]).fetch(100)
            logger.debug(f"{code = } yields <{len(discount_skels)}>{discount_skels = }")
            return discount_skels
        else:
            raise InvalidStateError

    def apply(
        self,
        code: str | None = None,
        discount_key: db.Key | None = None,
    ) -> t.Any:
        if not isinstance(code, (str, type(None))):
            raise TypeError(f"code must be an instance of str")
        if not isinstance(discount_key, (db.Key, type(None))):
            raise TypeError(f"discount_key must be an instance of db.Key")
        if not bool(code) ^ bool(discount_key):
            raise ValueError(f"Need code xor discount_code")
        cart_key = self.shop.cart.current_session_cart_key  # TODO: parameter?
        if cart_key is None:
            raise errors.PreconditionFailed("No basket created yet for this session")

        skels = self.search(code, discount_key)
        # logger.debug(f"{skels = }")

        if not skels:
            raise errors.NotFound
        for discount_skel in skels:
            logger.debug(f'{discount_skel["name"]=} // {discount_skel["description"]=}')
            # logger.debug(f"{discount_skel = }")
            applicable, dv = self.can_apply(discount_skel, cart_key=cart_key, code=code)
            if applicable:
                logger.debug("is applicable")
                break
            else:
                logger.error(f"{dv = }")
        else:
            raise errors.NotFound("No valid code found")

        logger.debug(f"Using {discount_skel=}")
        logger.debug(f"Using {dv=}")

        try:
            application_domain = dv.application_domain
        except KeyError:
            raise InvalidStateError("application_domain not set")

        if discount_skel["discount_type"] == DiscountType.FREE_ARTICLE:
            cart_node_skel = self.shop.cart.cart_add(
                parent_cart_key=cart_key,
                name="Free Article",
                discount_key=discount_skel["key"],
            )
            logger.debug(f"{cart_node_skel = }")
            cart_item_skel = self.shop.cart.add_or_update_article(
                article_key=discount_skel["free_article"]["dest"]["key"],
                parent_cart_key=cart_node_skel["key"],
                quantity=1,
                quantity_mode=QuantityMode.REPLACE,
            )
            logger.debug(f"{cart_item_skel = }")
            return {  # TODO: what should be returned?
                "discount_skel": discount_skel,
                "cart_node_skel": cart_node_skel,
                "cart_item_skel": cart_item_skel,
            }
        elif application_domain == ApplicationDomain.BASKET:
            if discount_skel["discount_type"] in {DiscountType.PERCENTAGE, DiscountType.ABSOLUTE}:
                cart = self.shop.cart.cart_update(
                    cart_key=cart_key,
                    discount_key=discount_skel["key"]
                )
                logger.debug(f"{cart = }")
                return {  # TODO: what should be returned?
                    "discount_skel": discount_skel,
                }
        elif application_domain == ApplicationDomain.ARTICLE:
            # In this case we use scope_article to find the article on which this discount should be applied
            all_leafs = []
            for cv in dv.condition_validator_instances:
                if cv.is_fulfilled and cv.condition_skel["scope_article"]:
                    leaf_skels = (
                        self.shop.cart.viewSkel("leaf").all()
                        .filter("parentrepo =", cart_key)
                        .filter(
                            "article.dest.__key__ IN",
                            [article["dest"]["key"] for article in cv.condition_skel["scope_article"]]
                        )
                        .fetch()
                    )
                    logger.debug(f"<{len(leaf_skels)}>{leaf_skels = }")
                    # if not leaf_skels:
                    #     raise errors.NotFound("expected article is missing on cart")
                    # if len(leaf_skels) > 1:
                    #     raise NotImplementedError("article is ambiguous")
                    for leaf_skel in leaf_skels:
                        # Assign discount on new parent node for the leaf where the article is
                        parent_skel = self.shop.cart.viewSkel("node")
                        assert parent_skel.read(leaf_skel["parententry"])
                        if parent_skel["discount"] and parent_skel["discount"]["dest"]["key"] == discount_skel["key"]:
                            logger.info("Parent has already this discount key")
                            continue
                        parent_skel = self.shop.cart.add_new_parent(leaf_skel, name=f'Discount {discount_skel["name"]}')
                        cart = self.shop.cart.cart_update(
                            cart_key=parent_skel["key"],
                            discount_key=discount_skel["key"]
                        )
                        logger.debug(f"{cart = }")
                        all_leafs.append(leaf_skels)
            if not all_leafs:
                raise errors.NotFound("expected article is missing on cart (or discount exist already)")
            return {  # TODO: what should be returned?
                "leaf_skel": all_leafs,
                # "parent_skel": parent_skel,
                "discount_skel": discount_skel,
            }
        raise errors.NotImplemented(f'{discount_skel["discount_type"]=} is not implemented yet :(')

    def can_apply(
        self,
        skel: SkeletonInstance_T[DiscountSkel],
        *,
        cart_key: db.Key | None = None,
        article_skel: SkeletonInstance | None = None,
        code: str | None = None,
        context: DiscountValidationContext = DiscountValidationContext.NORMAL,
    ) -> tuple[bool, DiscountValidator | None]:
        logger.debug(f"--- Calling can_apply() ---")
        logger.debug(f'{skel["name"] = } // {skel["description"] = }')
        # logger.debug(f"{skel = }")

        if cart_key is None:
            cart = None
        else:
            cart = self.shop.cart.viewSkel("node")
            if not cart.read(cart_key):
                raise errors.NotFound

        if context == DiscountValidationContext.NORMAL and skel["activate_automatically"]:
            logger.info(f"looking for not automatically, but is automatically discount")
            return False, None

        dv = DiscountValidator()(
            cart_skel=cart, article_skel=article_skel,
            discount_skel=skel, code=code,
            context=context,
        )
        # logger.debug(f"{dv.is_fulfilled=} | {dv=}")

        if DEBUG_DISCOUNTS.get():
            # Use a buffer to make sure we write it on-block
            buffer = io.StringIO()
            print(f'Checking {skel["key"]!r} {skel["name"]}', file=buffer)
            for cv in dv.condition_validator_instances:
                code = f"{'+' if cv.is_fulfilled else '-'}"
                print(f'  {code} {dv.__class__.__name__} : '
                      f'{cv.condition_skel["key"]!r} {cv.condition_skel["name"]}', file=buffer)
                for s in cv.scope_instances:
                    code = f"{'+' if s.is_applicable else '-'}/{'+' if s.is_fulfilled else '-'}"
                    print(f"    {code} {s.__class__.__name__} : {s.is_applicable=} | {s.is_fulfilled=}", file=buffer)
            print(f">>> {dv.is_fulfilled=}", file=buffer)
            print(buffer.getvalue(), end="", flush=True)

        return dv.is_fulfilled, dv

    @property
    @cachetools.cached(cache=cachetools.TTLCache(maxsize=1024, ttl=3600))
    def current_automatically_discounts(self) -> list[SkeletonInstance_T[DiscountSkel]]:
        query = self.viewSkel().all().filter("activate_automatically =", True)
        discounts = []
        for skel in query.fetch(100):
            if not self.can_apply(skel, context=DiscountValidationContext.AUTOMATICALLY_PREVALIDATE)[0]:
                logger.debug(f'Skipping discount {skel["key"]} {skel["name"]} for current_automatically_discounts')
                continue
            discounts.append(skel)
        logger.debug(f'current_automatically_discounts {discounts=}')
        return discounts

    def remove(
        self,
        discount_key: db.Key,
    ) -> t.Any:
        if not isinstance(discount_key, db.Key):
            raise TypeError(f"discount_key must be an instance of db.Key")
        cart_key = self.shop.cart.current_session_cart_key  # TODO: parameter?

        discount_skel = self.viewSkel()

        if not discount_skel.read(discount_key):
            raise errors.NotFound
        try:
            # Todo what we do when we have more than more condition
            application_domain = discount_skel["condition"][0]["dest"]["application_domain"]
        except KeyError:
            raise InvalidStateError("application_domain not set")

        if discount_skel["discount_type"] == DiscountType.FREE_ARTICLE:
            for cart_skel in self.shop.cart.get_children(parent_cart_key=cart_key):
                if cart_skel["discount"] and cart_skel["discount"]["dest"]["key"] == discount_skel["key"]:
                    break
            else:
                raise errors.NotFound
            self.shop.cart.cart_remove(
                cart_key=cart_skel["key"]
            )

            return {  # TODO: what should be returned?
                "discount_skel": discount_skel}

        elif application_domain == ApplicationDomain.BASKET:
            self.shop.cart.cart_update(
                cart_key=cart_key,
                discount_key=None
            )
            return {  # TODO: what should be returned?
                "discount_skel": discount_skel,
            }

        elif application_domain == ApplicationDomain.ARTICLE:
            node_skels = (
                self.shop.cart.viewSkel("node").all()
                .filter("parentrepo =", cart_key)
                .filter("discount.dest.__key__ =", discount_key)
                .fetch(100)
            )

            # logger.debug(f"<{len(node_skels)}>{node_skels=}")
            for node_skel in node_skels:
                # TODO: remove node, if no custom name, shipping, etc. is set? remove_parent flag?
                self.shop.cart.cart_update(
                    cart_key=node_skel["key"],
                    discount_key=None,
                )
            if not node_skels:
                raise errors.NotFound("Discount not used by any cart")
            return {  # TODO: what should be returned?
                "node_skels": node_skels,
                "discount_skel": discount_skel,
            }

        raise errors.NotImplemented(f'{discount_skel["discount_type"]=} is not implemented yet :(')
