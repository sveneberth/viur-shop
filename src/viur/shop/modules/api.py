import logging

from google.protobuf.message import DecodeError

import viur.shop.exceptions as e
from viur.core import conf, db, errors, exposed, force_post
from viur.core.render.json.default import DefaultRender as JsonRenderer
from viur.shop.exceptions import InvalidKeyException
from viur.shop.modules.abstract import ShopModuleAbstract
from viur.shop.response_types import JsonResponse
from ..constants import CartType, QuantityMode, QuantityModeType

logger = logging.getLogger("viur.shop").getChild(__name__)


# TODO: add methods
# TODO: add permission concept
# TODO: add @force_post to not-view methods

class Api(ShopModuleAbstract):

    @property
    def json_renderer(self) -> JsonRenderer:
        return conf.main_app.vi.shop.render

    @exposed
    def article_view(
        self,
        article_key: str | db.Key,
        parent_cart_key: str | db.Key,
    ):
        """View an article in the cart"""
        article_key = self._normalize_external_key(
            article_key, "article_key")
        parent_cart_key = self._normalize_external_key(
            parent_cart_key, "parent_cart_key")
        if not (res := self.shop.cart.get_article(article_key, parent_cart_key)):
            raise errors.NotFound(f"{parent_cart_key} has no article with {article_key=}")
        return JsonResponse(res)

    @exposed
    @force_post
    def article_add(
        self,
        *,
        article_key: str | db.Key,
        quantity: int = 1,
        quantity_mode: QuantityModeType = "replace",
        parent_cart_key: str | db.Key,
    ):
        """Add an article to the cart"""
        article_key = self._normalize_external_key(
            article_key, "article_key")
        parent_cart_key = self._normalize_external_key(
            parent_cart_key, "parent_cart_key")
        try:
            quantity_mode = QuantityMode(quantity_mode)
        except ValueError:
            raise e.InvalidArgumentException("quantity_mode", quantity_mode)
        # TODO: Could also return self.article_view() or just the cart_node_key...
        return JsonResponse(self.shop.cart.add_or_update_article(
            article_key, parent_cart_key, quantity, quantity_mode))

    @exposed
    @force_post
    def article_update(
        self,
        *,
        article_key: str | db.Key,
        quantity: int,
        quantity_mode: QuantityModeType = "replace",
        parent_cart_key: str | db.Key,
    ):
        """Update an existing article in the cart"""
        article_key = self._normalize_external_key(
            article_key, "article_key")
        parent_cart_key = self._normalize_external_key(
            parent_cart_key, "parent_cart_key")
        try:
            quantity_mode = QuantityMode(quantity_mode)
        except ValueError:
            raise e.InvalidArgumentException("quantity_mode", quantity_mode)
        if not self.shop.cart.get_article(article_key, parent_cart_key):
            raise errors.NotFound(f"{parent_cart_key} has no article with {article_key=}")
        # TODO: Could also return self.article_view() or just the cart_node_key...
        return JsonResponse(self.shop.cart.add_or_update_article(
            article_key, parent_cart_key, quantity, quantity_mode))

    @exposed
    @force_post
    def article_remove(
        self,
        *,
        article_key: str | db.Key,
        parent_cart_key: str | db.Key,
    ):
        """Remove an article from the cart"""
        return self.article_update(article_key, 0, parent_cart_key)

    @exposed
    @force_post
    def article_move(
        self,
        *,
        article_key: str | db.Key,
        parent_cart_key: str | db.Key,
        new_parent_cart_key: str | db.Key,
    ):
        """Move an article inside a cart"""
        article_key = self._normalize_external_key(
            article_key, "article_key")
        parent_cart_key = self._normalize_external_key(
            parent_cart_key, "parent_cart_key")
        new_parent_cart_key = self._normalize_external_key(
            new_parent_cart_key, "new_parent_cart_key")
        return JsonResponse(self.shop.cart.article_move(
            article_key, parent_cart_key, new_parent_cart_key))

    @exposed
    @force_post
    def cart_add(
        self,
        *,
        parent_cart_key: str | db.Key = None,
        cart_type: CartType = None,  # TODO: since we generate basket automatically,
        #                                    wishlist would be the only acceptable value ...
        name: str = None,
        customer_comment: str = None,
        shipping_address_key: str | db.Key = None,
        shipping_key: str | db.Key = None,
    ):
        parent_cart_key = self._normalize_external_key(
            parent_cart_key, "parent_cart_key")
        if cart_type is not None:
            try:
                cart_type = CartType(cart_type)
            except ValueError:
                raise e.InvalidArgumentException("cart_type", cart_type)
        return JsonResponse(self.shop.cart.cart_add(
            parent_cart_key, cart_type, name, customer_comment,
            shipping_address_key, shipping_key))

    @exposed
    @force_post
    def cart_update(
        self,
        *,
        cart_key: str | db.Key,
        name: str = None,
        customer_comment: str = None,
        shipping_address_key: str | db.Key = None,
        shipping_key: str | db.Key = None,
    ):
        ...

    @exposed
    @force_post
    def cart_remove(
        self,
        *,
        cart_key: str | db.Key,
    ):
        """Remove itself and all children"""
        cart_key = self._normalize_external_key(cart_key, "cart_key")
        return JsonResponse(self.shop.cart.cart_remove(cart_key))

    @exposed
    @force_post
    def cart_clear(
        self,
        *,
        cart_key: str | db.Key,
        remove_sub_carts: bool = False,
    ):
        """Remove direct or all children

        :param remove_sub_carts: Remove child leafs, keep nodes
        """
        cart_key = self._normalize_external_key(cart_key, "cart_key")
        ...

    @exposed
    def cart_list(
        self,
        cart_key: str | db.Key | None = None,
    ):
        """
        List root nodes or children of a cart

        If a cart key is provided, the direct children (nodes and leafs) will
        be returned.
        Otherwise (without a key), the root nodes will be returned.

        cart_key: list direct children (nodes and leafs) of this parent node
        """
        # no key: list root node
        if cart_key is None:
            return JsonResponse(self.shop.cart.getAvailableRootNodes())
        # key provided: list children (nodes and leafs)
        cart_key = self._normalize_external_key(cart_key, "cart_key")
        children = []
        for child_skel in self.shop.cart.get_children(cart_key):
            assert issubclass(child_skel.skeletonCls, (self.shop.cart.nodeSkelCls, self.shop.cart.leafSkelCls))
            child = self.json_renderer.renderSkelValues(child_skel)
            child["skel_type"] = "leaf" if issubclass(child_skel.skeletonCls, self.shop.cart.leafSkelCls) else "node"
            children.append(child)
        return JsonResponse(children)

    @exposed
    @force_post
    def order_add(
        self,
        *,
        cart_key: str | db.Key,
        payment_provider: str = None,
        billing_address_key: str | db.Key = None,
        email: str = None,
        customer_key: str | db.Key = None,
        state_ordered: bool = None,
        state_paid: bool = None,
        state_rts: bool = None,
    ):
        cart_key = self._normalize_external_key(cart_key, "cart_key")
        billing_address_key = self._normalize_external_key(billing_address_key, "billing_address_key")
        customer_key = self._normalize_external_key(customer_key, "customer_key")
        ...
        return JsonResponse(self.shop.order.order_add(
            cart_key, payment_provider, billing_address_key,
            email, customer_key, state_ordered, state_paid, state_rts))

    @exposed
    @force_post
    def order_update(
        self,
        *,
        order_key: str | db.Key,
        payment_provider: str = None,
        billing_address_key: str | db.Key = None,
        email: str = None,
        customer_key: str | db.Key = None,
        state_ordered: bool = None,
        state_paid: bool = None,
        state_rts: bool = None,
    ):
        ...

    @exposed
    @force_post
    def order_remove(
        self,
        *,
        order_key: str | db.Key,
    ):
        ...

    @exposed
    @force_post
    def order_view(
        self,
        order_key: str | db.Key,
    ):
        """
        Gibt gesetzte Werte (BillAddress) aus und gibt computed Wert "is_orderable" aus,
        ob alle Vorbedingungen für Bestellabschluss erfüllt sind.
        """
        ...

    @exposed
    @force_post
    def discount_add(
        self,
        *,
        code: str,
        discount_key: str | db.Key,
    ):
        """
        parameter code xor discount_key: str | db.Key

        Sucht nach Rabatt mit dem code xor key, je nach Typ (Artikel/Warenkorb) suche ...ende parent_node oder erzeuge eine und setze dort die discount Relation.
        """
        ...

    @exposed
    @force_post
    def discount_remove(
        self,
        *,

        discount_key: str | db.Key,
    ):
        ...

    @exposed
    def shipping_list(
        self,
        cart_key: str | db.Key,
    ):
        """
        Listet verfügbar Versandoptionen für einen (Unter)Warenkorb auf
        """
        ...

    # --- Internal helpers  ----------------------------------------------------

    def _normalize_external_key(
        self,
        external_key: str,
        parameter_name: str,
    ) -> db.Key:
        """
        Convert urlsafe key to db.Key and raise an error on invalid in key.
        """
        try:
            return db.Key.from_legacy_urlsafe(external_key)
        except DecodeError:  # yes, the exception really comes from protobuf...
            raise InvalidKeyException(external_key, parameter_name)

    # --- Testing only --------------------------------------------------------

    @exposed
    def tmp_article_list(self):  # TODO testing only
        return [
            skel["shop_name"]
            for skel in self.shop.article_skel().all().fetch()
        ]

    @exposed
    def tmp_article_gen(self):  # TODO testing only
        for i in range(10):
            skel = self.shop.article_skel()
            skel["shop_name"] = f"Article #{str(i).zfill(5)}"
            skel.toDB()
            logger.info(f"Added article skel {skel}")


Api.html = True
Api.vi = True
