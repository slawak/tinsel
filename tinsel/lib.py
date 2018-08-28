from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal
# noinspection PyProtectedMember
from typing import _Union as UnionType
from typing import Optional, Union, GenericMeta, List, Tuple, Dict

from pyspark.sql import types as t

from tinsel.types import NoneType, byte, short, long, T, T_co, FunctorLike


def is_pyspark_class(cls: type) -> bool:
    return getattr(cls, "__pyspark_struct__", None) is ...


def is_typed_namedtuple(cls: type) -> bool:
    fields = getattr(cls, "_fields", None)
    annotations = getattr(cls, "__annotations__", None)
    return isinstance(fields, tuple) and isinstance(annotations, OrderedDict)


def struct(cls: type) -> type:
    if not is_typed_namedtuple(cls):
        raise ValueError(f"Only NamedTuple instances can be decorated with @struct, not {cls.__name__}")
    cls.__pyspark_struct__ = ...
    return cls


def check_pyspark_struct(cls: type):
    if not isinstance(cls, type):
        raise TypeError(f"Expected type, but got instance {cls} of type {type(cls).__name__}")
    if is_typed_namedtuple(cls):
        if not is_pyspark_class(cls):
            raise ValueError(f"Looks like type {cls.__name__} missed @struct decorator")
    else:
        raise ValueError(f"Type {cls.__name__} can't be used as structure")


def infer_nullability(typeclass) -> bool:
    return isinstance(typeclass, UnionType) and NoneType in set(typeclass.__args__)


def unlift_optional(typeclass: Optional[T]) -> T:
    return list(set(typeclass.__args__) - {NoneType})[0]


def maybe_unlift_optional(typeclass: Union[T_co, FunctorLike[T_co]]) -> Tuple[bool, T_co]:
    is_nullable = infer_nullability(typeclass)
    return is_nullable, (unlift_optional(typeclass) if is_nullable else typeclass)


def infer_complex_spark_type(typeclass):
    if typeclass.__origin__ is List:
        co_T, *_ = typeclass.__args__
        is_nullable, py_type = maybe_unlift_optional(co_T)
        return t.ArrayType(infer_spark_type(py_type), is_nullable)
    elif typeclass.__origin__ is Dict:
        k_T, v_T, *_ = typeclass.__args__
        is_nullable_key, py_key_type = maybe_unlift_optional(k_T)
        is_nullable_value, py_value_type = maybe_unlift_optional(v_T)
        if is_nullable_key:
            raise TypeError(f"Nullable keys of type {py_key_type} don't allowed in {typeclass}")
        return t.MapType(infer_spark_type(py_key_type), infer_spark_type(py_value_type), is_nullable_value)
    else:
        raise TypeError(f"Don't know how to represent {typeclass} in Spark")


def infer_spark_type(typeclass) -> t.DataType:
    if typeclass is NoneType:
        return t.NullType()
    elif typeclass is str:
        return t.StringType()
    elif typeclass in {bytes, bytearray}:
        return t.BinaryType()
    elif typeclass is bool:
        return t.BooleanType()
    elif typeclass is date:
        return t.DateType()
    elif typeclass is datetime:
        return t.TimestampType()
    elif typeclass is Decimal:
        return t.DecimalType(precision=36, scale=6)
    elif typeclass is float:
        return t.DoubleType()
    elif typeclass is int:
        return t.IntegerType()
    elif typeclass is long:
        return t.LongType()
    elif typeclass is short:
        return t.ShortType()
    elif typeclass is byte:
        return t.ByteType()
    elif "__origin__" in typeclass.__dict__:
        return infer_complex_spark_type(typeclass)
    elif is_pyspark_class(typeclass):
        return transform(typeclass)
    else:
        raise TypeError(f"Don't know how to represent {typeclass} in Spark")


def transform_field(name: str, typeclass: Union[type, GenericMeta]) -> t.StructField:
    (is_nullable, unwrapped_py_type) = maybe_unlift_optional(typeclass)
    return t.StructField(name, infer_spark_type(unwrapped_py_type), is_nullable)


def transform(typeclass: Union[type, GenericMeta]) -> t.StructType:
    """
    Infer PySpark SQL types from namedtuple class fields

    :param typeclass: @struct-annotated NamedTuple class
    :return: PySpark data structure
    """
    check_pyspark_struct(typeclass)
    return t.StructType([
        transform_field(name, cls)
        for name, cls
        in typeclass.__annotations__.items()
    ])