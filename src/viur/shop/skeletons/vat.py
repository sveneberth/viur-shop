import typing as t  # noqa

from viur.core.bones import *
from viur.core.skeleton import Skeleton
from ..globals import SHOP_LOGGER

logger = SHOP_LOGGER.getChild(__name__)


class VatSkel(Skeleton):  # STATE: Complete (as in model)
    kindName = "shop_vat"

    # TODO: add descr bone?!

    name = StringBone(
        descr="name",
        compute=Compute(lambda skel: f'{skel["rate"]} %')
    )

    rate = NumericBone(
        descr="rate",
        required=True,
        precision=2,
        min=0,
        getEmptyValueFunc=lambda: None,
        # TODO: UnitBone / PercentageBone
    )
