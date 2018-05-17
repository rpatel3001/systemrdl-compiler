from copy import deepcopy
from . import type_placeholders as tp
from .. import component as comp
from .. import rdltypes


class Expr:
    def __init__(self, compiler, err_ctx):
        self.compiler = compiler
        self.msg = compiler.msg
        
        # Number of bits to use for this expression's evaluation
        # Only relevant for integer-like contexts
        self.expr_eval_width = None
        
        # operands of the expression
        self.op = []
        
        # Handle to Antlr object to use for error context
        self.err_ctx = err_ctx
    
    def __deepcopy__(self, memo):
        """
        Deepcopy all members except for ones that should be copied by reference
        """
        copy_by_ref = ["err_ctx", "compiler", "msg"]
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if(k in copy_by_ref):
                setattr(result, k, v)
            else:
                setattr(result, k, deepcopy(v, memo))
        return(result)
    
    def trunc(self, v):
        mask = (1 << self.expr_eval_width) - 1
        return(v & mask)
        
    def predict_type(self):
        """
        Returns the expected type of the result of the expression
        This function shall call any child expression's predict_type()
        even if the child type is not relevant to the resulting type.
        Raises exception if input types are not compatible.
        """
        raise NotImplementedError
    
    def resolve_expr_width(self):
        """
        Each integer-like expression context is evaluated in a self-determined
        bit width.
        
        This function is called for the top-node of each expression context
        in order to determine, and propagate the context's expression width
        - Determine the context's expression width from all
          operands that do not define their own context.
        - Propagate resulting width back to those same ops
        """
        self.expr_eval_width = 1
        for op in self.op:
            w = op.get_min_eval_width()
            self.expr_eval_width = max(self.expr_eval_width, w)
        
        for op in self.op:
            op.propagate_eval_width(self.expr_eval_width)
        
    def get_min_eval_width(self):
        """
        Returns the expressions resulting integer width based on the
        self-determined expression bit-width rules
        (SystemVerilog LRM: IEEE Std 1800-2012, Table 11-21)
        """
        raise NotImplementedError
    
    def propagate_eval_width(self, w):
        """
        Sets the new expression evaluation width from the parent context
        If this expression is the beginning of a new self-determined integer
        context, then it shall override this and:
            - Ignore the value w
            - Instead, call self.resolve_expr_width() in order to continue
              resolution propagation
        """
        self.expr_eval_width = w
        for op in self.op:
            op.propagate_eval_width(w)
        
    def get_value(self):
        """
        Compute the value of the result of the expression
        Assumed that types are compatible.
        """
        raise NotImplementedError
    
#-------------------------------------------------------------------------------
class IntLiteral(Expr):
    def __init__(self, compiler, err_ctx, val, width=64):
        super().__init__(compiler, err_ctx)
        self.val = val
        self.width = width
    
    def predict_type(self):
        return(int)
        
    def get_min_eval_width(self):
        return(self.width)
    
    def get_value(self):
        return(self.val)

#-------------------------------------------------------------------------------
class BuiltinEnumLiteral(Expr):
    """
    Expr wrapper for builtin RDL enumeration types:
    AccessType, OnReadType, OnWriteType, AddressingType, PrecedenceType
    """
    def __init__(self, compiler, err_ctx, val):
        super().__init__(compiler, err_ctx)
        self.val = val
    
    def predict_type(self):
        return(type(self.val))
        
    def get_min_eval_width(self):
        return(1) # dont care
    
    def get_value(self):
        return(self.val)

#-------------------------------------------------------------------------------
class StringLiteral(Expr):
    def __init__(self, compiler, err_ctx, val):
        super().__init__(compiler, err_ctx)
        self.val = val
    
    def predict_type(self):
        return(str)
        
    def get_min_eval_width(self):
        return(1) # dont care
    
    def get_value(self):
        return(self.val)

#-------------------------------------------------------------------------------
# Integer binary operators:
#   +  -  *  /  %  &  |  ^  ^~  ~^
# Normal expression context rules
class _BinaryIntExpr(Expr):
    def __init__(self, compiler, err_ctx, l, r):
        super().__init__(compiler, err_ctx)
        self.op = [l, r]
        
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Left operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        if(self.op[1].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Right operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        return(int)
    
    def get_min_eval_width(self):
        return(max(
            self.op[0].get_min_eval_width(),
            self.op[1].get_min_eval_width()
        ))
        
    def get_ops(self):
        l = int(self.op[0].get_value())
        r = int(self.op[1].get_value())
        return(l,r)
    
class Add(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l + r))

class Sub(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l - r))

class Mult(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l * r))

class Div(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        if(r == 0):
            self.msg.fatal(
                "Division by zero",
                self.err_ctx
            )
        return(self.trunc(l // r))

class Mod(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        if(r == 0):
            self.msg.fatal(
                "Modulo by zero",
                self.err_ctx
            )
        return(self.trunc(l % r))
        
class BitwiseAnd(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l & r))
        
class BitwiseOr(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l | r))
        
class BitwiseXor(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l ^ r))

class BitwiseXnor(_BinaryIntExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l ^~ r))

#-------------------------------------------------------------------------------
# Integer unary operators:
#   +  -  ~
# Normal expression context rules
class _UnaryIntExpr(Expr):
    def __init__(self, compiler, err_ctx, n):
        super().__init__(compiler, err_ctx)
        self.op = [n]
        
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        return(int)
    
    def get_min_eval_width(self):
        return(self.op[0].get_min_eval_width())
        
    def get_ops(self):
        n = int(self.op[0].get_value())
        return(n)

class UnaryPlus(_UnaryIntExpr):
    def get_value(self):
        n = self.get_ops()
        return(self.trunc(n))

class UnaryMinus(_UnaryIntExpr):
    def get_value(self):
        n = self.get_ops()
        return(self.trunc(-n))

class BitwiseInvert(_UnaryIntExpr):
    def get_value(self):
        n = self.get_ops()
        return(self.trunc(~n))

#-------------------------------------------------------------------------------
# Relational operators:
#   == != < > <= >=
# Result is always 1 bit bool
# Creates a new evaluation context
# Child operands are evaluated in the same width context, sized to the max
# of either op.
class _RelationalExpr(Expr):
    def __init__(self, compiler, err_ctx, l, r):
        super().__init__(compiler, err_ctx)
        self.op = [l, r]
        # TODO: add support for non-numeric comparisons
        
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Left operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        if(self.op[1].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Right operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        return(bool)
    
    def get_min_eval_width(self):
        return(1)
        
    def propagate_eval_width(self, w):
        """
        Ignore parent's width and start a new expression context
        """
        self.resolve_expr_width()
        
    def get_ops(self):
        l = int(self.op[0].get_value())
        r = int(self.op[1].get_value())
        return(l,r)
        
class Eq(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l == r)

class Neq(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l != r)

class Lt(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l < r)
        
class Gt(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l > r)

class Leq(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l <= r)

class Geq(_RelationalExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l >= r)

#-------------------------------------------------------------------------------
# Reduction operators:
#   &  ~&  |  ~|  ^  ^~  !
# Result is always 1 bit bool
# Creates a new evaluation context
class _ReductionExpr(Expr):
    def __init__(self, compiler, err_ctx, n):
        super().__init__(compiler, err_ctx)
        self.op = [n]
    
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        return(int)
    
    def get_min_eval_width(self):
        return(1)
        
    def propagate_eval_width(self, w):
        """
        Ignore parent's width and start a new expression context
        """
        self.resolve_expr_width()
        
    def get_ops(self):
        n = int(self.op[0].get_value())
        return(n)

class AndReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        n = self.trunc(~n)
        return(int(n == 0))
        
class NandReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        return(int(n != 0))
        
class OrReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        return(int(n != 0))
        
class NorReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        return(int(n == 0))

class XorReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        v = 0
        while(n):
            if(n & 1):
                v ^= 1
            n >>= 1
        return(v)

class XnorReduce(_ReductionExpr):
    def get_value(self):
        n = self.get_ops()
        v = 1
        while(n):
            if(n & 1):
                v ^= 1
            n >>= 1
        return(v)
        
class BoolNot(_ReductionExpr):
    def get_value(self):
        return(not self.op[0])

#-------------------------------------------------------------------------------
# Logical boolean operators:
#   && ||
# Both operands are self-determined
class _BoolExpr(Expr):
    def __init__(self, compiler, err_ctx, l, r):
        super().__init__(compiler, err_ctx)
        self.op = [l,r]
    
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Left operand of expression is not a compatible boolean type",
                self.err_ctx
            )
        if(self.op[1].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Right operand of expression is not a compatible boolean type",
                self.err_ctx
            )
        return(bool)
    
    def resolve_expr_width(self):
        # All operands are self determined. Do nothing
        pass
    
    def get_min_eval_width(self):
        return(1)
    
    def propagate_eval_width(self, w):
        """
        Eval width is ignored. Trigger expression width
        resolution for both operand since they are self-determined
        """
        self.op[0].resolve_expr_width()
        self.op[1].resolve_expr_width()
    
    def get_ops(self):
        l = bool(self.op[0].get_value())
        r = bool(self.op[1].get_value())
        return(l,r)
        
class BoolAnd(_BoolExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l and r)
        
class BoolOr(_BoolExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(l or r)
        
#-------------------------------------------------------------------------------
# Exponent & shift operators:
#   **  <<  >>
# Righthand operand is self-determined
class _ExpShiftExpr(Expr):
    def __init__(self, compiler, err_ctx, l, r):
        super().__init__(compiler, err_ctx)
        self.op = [l,r]
    
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Left operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        if(self.op[1].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Right operand of expression is not a compatible numeric type",
                self.err_ctx
            )
        return(int)
    
    def resolve_expr_width(self):
        """
        Eval width only depends on the first operand
        """
        self.expr_eval_width = self.op[0].get_min_eval_width()
        self.op[0].propagate_eval_width(self.expr_eval_width)
    
    def get_min_eval_width(self):
        # Righthand op has no influence in evaluation context
        return(self.op[0].get_min_eval_width())
    
    def propagate_eval_width(self, w):
        """
        Propagate eval width as usual, but also trigger expression width
        resolution for righthand operand since it is self-determined
        """
        self.expr_eval_width = w
        self.op[0].propagate_eval_width(w)
        
        self.op[1].resolve_expr_width()
    
    def get_ops(self):
        l = int(self.op[0].get_value())
        r = int(self.op[1].get_value())
        return(l,r)
    
class Exponent(_ExpShiftExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(int(l ** r)))

class LShift(_ExpShiftExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l << r))

class RShift(_ExpShiftExpr):
    def get_value(self):
        l,r = self.get_ops()
        return(self.trunc(l >> r))

#-------------------------------------------------------------------------------
# Ternary conditional operator
#   i ? j : k
# Truth expression is self-determined and does not contribute to context

class TernaryExpr(Expr):
    def __init__(self, compiler, err_ctx, i, j, k):
        super().__init__(compiler, err_ctx)
        self.op = [i, j, k]
    
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Conditional operand of expression is not a compatible boolean type",
                self.err_ctx
            )
        
        # Type of j and k shall be compatible
        t_j = self.op[1].predict_type()
        t_k = self.op[2].predict_type()
        
        num_t = [int, bool]
        if((t_j in num_t) and (t_k in num_t)):
            # Both are a numeric type
            return(int)
        else:
            # Not numeric types. Shall be equal types
            if(t_j != t_k):
                self.msg.fatal(
                    "True/False results of ternary conditional are not compatible types",
                    self.err_ctx
                )
            return(t_j)
    
    def resolve_expr_width(self):
        wj = self.op[1].get_min_eval_width()
        wk = self.op[2].get_min_eval_width()
        self.expr_eval_width = max(1, wj, wk)
        
        self.op[1].propagate_eval_width(self.expr_eval_width)
        self.op[2].propagate_eval_width(self.expr_eval_width)
    
    def get_min_eval_width(self):
        # Truth operand has no influence in evaluation context
        return(max(
            self.op[1].get_min_eval_width(),
            self.op[2].get_min_eval_width()
        ))
    
    def propagate_eval_width(self, w):
        """
        Propagate eval width as usual, but also trigger expression width
        resolution for truth operand since it is self-determined
        """
        self.expr_eval_width = w
        self.op[1].propagate_eval_width(w)
        self.op[2].propagate_eval_width(w)
        
        self.op[0].resolve_expr_width()
    
    def get_value(self):
        i = bool(self.op[0].get_value())
        j = self.op[1].get_value()
        k = self.op[2].get_value()
        
        if(i):
            return(j)
        else:
            return(k)

#-------------------------------------------------------------------------------
# Width cast operator
# the cast type informs the parser what width to cast to
# The cast width determines the result's width
# Also influences the min eval width of the value expression
class WidthCast(Expr):
    def __init__(self, compiler, err_ctx, v, w_expr=None, w_int=64):
        super().__init__(compiler, err_ctx)
        
        if(w_expr is not None):
            self.op = [v, w_expr]
            self.cast_width = None
        else:
            self.op = [v]
            self.cast_width = w_int
        
    def predict_type(self):
        if(self.cast_width is None):
            if(self.op[1].predict_type() not in [int, bool]):
                self.msg.fatal(
                    "Width operand of cast expression is not a compatible numeric type",
                    self.err_ctx
                )
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Value operand of cast expression cannot be cast to an integer",
                self.err_ctx
            )
        
        return(int)
    
    def resolve_expr_width(self):
        self.resolve_cast_width()
        self.expr_eval_width = self.cast_width
        w = self.op[0].get_min_eval_width()
        self.expr_eval_width = max(self.expr_eval_width, w)
        self.op[0].propagate_eval_width(self.expr_eval_width)
    
    def get_min_eval_width(self):
        self.resolve_cast_width()
        return(self.cast_width)
        
    def propagate_eval_width(self, w):
        """
        Ignore parent's width and start a new expression context using
        the cast's width
        """
        self.resolve_expr_width()
    
    def resolve_cast_width(self):
        if(self.cast_width is None):
            # Need to force evaluation of the width value in order to proceed
            self.op[1].resolve_expr_width()
            self.cast_width = self.op[1].get_value()
    
    def get_value(self):
        # Truncate to cast width instead of eval width
        n = int(self.op[0].get_value())
        self.expr_eval_width = self.cast_width
        if(self.expr_eval_width == 0):
            self.msg.fatal(
                "Cannot cast to width of zero",
                self.err_ctx
            )
        return(self.trunc(n))

#-------------------------------------------------------------------------------
# Boolean cast operator

class BoolCast(Expr):
    def __init__(self, compiler, err_ctx, n):
        super().__init__(compiler, err_ctx)
        self.op = [n]
    
    def predict_type(self):
        if(self.op[0].predict_type() not in [int, bool]):
            self.msg.fatal(
                "Value operand of cast expression cannot be cast to a boolean",
                self.err_ctx
            )
        return(bool)
    
    def get_min_eval_width(self):
        return(1)
        
    def propagate_eval_width(self, w):
        """
        Ignore parent's width and start a new expression context
        """
        self.resolve_expr_width()
        
    def get_value(self):
        n = int(self.op[0].get_value())
        return(n != 0)

#-------------------------------------------------------------------------------
# References

class ParameterRef(Expr):
    def __init__(self, compiler, err_ctx, param):
        super().__init__(compiler, err_ctx)
        self.param = param
    
    def predict_type(self):
        return(self.param.param_type)
    
    def resolve_expr_width(self):
        if(self.param.expr is None):
            self.msg.fatal(
                "Value for parameter '%s' was never assigned" % self.param.name,
                self.err_ctx
            )
        self.op = [self.param.expr]
        super().resolve_expr_width()
    
    def get_min_eval_width(self):
        if(self.param.expr is None):
            self.msg.fatal(
                "Value for parameter '%s' was never assigned" % self.param.name,
                self.err_ctx
            )
        return(self.param.expr.get_min_eval_width())
    
    def propagate_eval_width(self, w):
        self.resolve_expr_width()
        
    def get_value(self):
        return(self.param.expr.get_value())


class InstRef(Expr):
    def __init__(self, compiler, ref_inst, uplevels_to_ref, ref_elements):
        super().__init__(compiler, None) # single err_ctx doesn't make sense for InstRef
        
        # Points to the component inst that the ref_elements 'path' is relative to
        self.ref_inst = ref_inst
        
        # Number of parents to traverse up from the assignee to reach ref_inst
        # For InstRefs in local property assignments, this is 0
        # For dynamic (hierarchical) property assignments, this is > 0
        self.uplevels_to_ref = uplevels_to_ref
        
        # List of hierarchical reference element tuples that make up the path
        # to the reference.
        # Path is relative to ref_inst
        # Each tuple in the list represents a segment of the path:
        # [
        #   ( <Antlr ID token> , [ <Index Expr> , ... ] ),
        #   ( <Antlr ID token> , [ <Index Expr> , ... ] )
        # ]
        self.ref_elements = ref_elements
    
    def __deepcopy__(self, memo):
        """
        Copy any Antlr tokens by ref within the ref_elements list when deepcopying
        """
        copy_by_ref = ["err_ctx", "compiler", "msg"]
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if(k in copy_by_ref):
                setattr(result, k, v)
            elif(k == "ref_elements"):
                # Manually deepcopy the ref_elements list
                new_ref_elements = []
                for src_name_token, src_array_suffixes in v:
                    new_array_suffixes = deepcopy(src_array_suffixes, memo)
                    new_ref_elements.append((src_name_token, new_array_suffixes))
                setattr(result, k, new_ref_elements)
            else:
                setattr(result, k, deepcopy(v, memo))
        return(result)
    
    def predict_type(self):
        """
        Traverse the ref_elements path and determine the component type being
        referenced.
        Also do some checks on the array indexes
        """
        current_inst = self.ref_inst
        for name_token, array_suffixes in self.ref_elements:
            name = name_token.getText()
            
            # find instance
            current_inst = current_inst.get_child_by_name(name)
            if(current_inst is None):
                # Not found!
                self.msg.fatal(
                    "Could not resolve hierarchical reference to '%s'" % name,
                    name_token
                )
            
            # Do type-check in array suffixes
            for array_suffix in array_suffixes:
                array_suffix.predict_type()
                
            # Check array suffixes
            if((issubclass(type(current_inst), comp.AddressableComponent)) and current_inst.is_array):
                # is an array
                if(len(array_suffixes) != len(current_inst.array_dimensions)):
                    self.msg.fatal(
                        "Incompatible number of index dimensions after '%s'. Expected %d, found %d."
                            % (name, len(current_inst.array_dimensions), len(array_suffixes)),
                        name_token
                    )
            elif(len(array_suffixes)):
                # Has array suffixes. Check if compatible with referenced component
                self.msg.fatal(
                    "Unable to index non-array component '%s'" % name,
                    name_token
                )
        
        return(type(current_inst))
        
    def resolve_expr_width(self):
        # Resolve expression widths of all array suffixes in ref_elements
        for name_token, array_suffixes in self.ref_elements:
            for array_suffix in array_suffixes:
                array_suffix.resolve_expr_width()
    
    def get_min_eval_width(self):
        return(1) # Don't care
    
    def propagate_eval_width(self, w):
        self.resolve_expr_width()
    
    def get_value(self):
        """
        Build a resolved ComponentRef container that describes the relative path
        """
        
        resolved_ref_elements = []
        
        current_inst = self.ref_inst
        for name_token, array_suffixes in self.ref_elements:
            name = name_token.getText()
            
            # find instance
            current_inst = current_inst.get_child_by_name(name)
            if(current_inst is None):
                raise RuntimeError
            
            # Evaluate array suffixes if appropriate
            idx_list = None
            if((issubclass(type(current_inst), comp.AddressableComponent)) and current_inst.is_array):
                idx_list = [ suffix.get_value() for suffix in array_suffixes ]
                
                # Check ranges on suffixes
                for i in range(len(idx_list)):
                    if(idx_list[i] >= current_inst.array_dimensions[i]):
                        self.msg.fatal(
                            "Array index out of range. Expected 0-%d, got %d."
                                % (current_inst.array_dimensions[i]-1, idx_list[i]),
                            array_suffix.err_ctx
                        )
            
            resolved_ref_elements.append((name, idx_list))
        
        # Create container
        cref = rdltypes.ComponentRef(self.uplevels_to_ref, resolved_ref_elements)
        
        return(cref)
        
#-------------------------------------------------------------------------------
# Assignment cast
# This is a wrapper expression that normalizes the expression result
# to the expected data type
# This wrapper forces the operand to be evaluated in a self-determined context
# The cast type has no effect on expression evaluation
# During post-compile:
#   Checks that the expression result is of a compatible type
#
# When getting value:
#   Ensures that the expression result gets converted to the resulting type
class AssignmentCast(Expr):
    def __init__(self, compiler, err_ctx, v, dest_type):
        super().__init__(compiler, err_ctx)
        
        self.op = [v]
        self.dest_type = dest_type
    
    def predict_type(self):
        op_type = self.op[0].predict_type()
        
        if(not is_type_compatible(op_type, self.dest_type)):
            self.msg.fatal(
                "Result of expression is not compatible with the expected type",
                self.err_ctx
            )
        
        return(self.dest_type)
    
    def get_min_eval_width(self):
        return(self.op[0].get_min_eval_width())
    
    def propagate_eval_width(self, w):
        self.resolve_expr_width()
    
    def get_value(self):
        v = self.op[0].get_value()
        
        if(self.dest_type == bool):
            return(bool(v))
        else:
            return(v)



#===============================================================================
def is_type_compatible(t1, t2):
    """
    Checks if the two types are compatible.
    """
    if((t1 in [int, bool]) and (t2 in [int, bool])):
        # Both came from number-like types.
        return(True)
    elif((t1 == tp.Array) and (t2 == tp.Array)):
        # TODO: Check that array size and element types also match
        raise NotImplementedError
    elif(t1 == t2):
        return(True)
    else:
        return(False)