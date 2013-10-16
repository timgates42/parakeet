from collections import namedtuple

from .. import names, prims  
from ..ndtypes import (IntT, FloatT, TupleT, FnT, Type, BoolT, NoneT, Float32, Float64, Bool, 
                       ClosureT, ScalarT, PtrT, NoneType)    
from ..syntax import (Const, Var,  PrimCall, Attribute, TupleProj, Tuple, ArrayView,
                      Expr, Closure, TypedFn)
from ..syntax.helpers import get_types   
import type_mappings
from base_compiler import BaseCompiler


CompiledFlatFn = namedtuple("CompiledFlatFn", 
                            ("name", "sig", "src",
                             "extra_objects",
                             "extra_functions",
                             "extra_function_signatures", 
                             "declarations"))


class FlatFnCompiler(BaseCompiler):
  
  def __init__(self, struct_type_cache = None):
    BaseCompiler.__init__(self)
    
    
    self.declarations = []
    
    # depends on these .o files
    self.extra_objects = set([]) 
    
    # to avoid adding the same function's source twice 
    # we use its signature as a key  
    self.extra_functions = {}
    self.extra_function_signatures = []
    
    if struct_type_cache is None:
      # don't create more than one struct type per tuple type
      self._tuple_struct_cache = {}
    else:
      self._tuple_struct_cache = struct_type_cache
  
  def add_decl(self, decl):
    if decl not in self.declarations:
      self.declarations.append(decl)
  
  def struct_type_from_fields(self, field_types):
    
    if any(not isinstance(t, str) for t in field_types):
      field_types = tuple(self.to_ctype(t) if isinstance(t, Type) else t 
                          for t in field_types)
    else:
      field_types = tuple(field_types)
    
    if field_types in self._tuple_struct_cache:
      return self._tuple_struct_cache[field_types]
    
    typename = names.fresh("tuple_type").replace(".", "_")

    field_decls = ["  %s %s;" % (t, "elt%d" % i) for i,t in enumerate(field_types)]
    decl = "typedef struct %s {\n%s\n} %s;" % (typename, "\n".join(field_decls), typename)
    self.add_decl(decl)
    self._tuple_struct_cache[field_types] = typename
    return typename 
  
  
  def to_ctypes(self, ts):
    return tuple(self.to_ctype(t) for t in ts)
  
  def to_ctype(self, t):
    if isinstance(t, TupleT):
      elt_types = self.to_ctypes(t.elt_types)
      return self.struct_type_from_fields(elt_types) 
    else:
      return type_mappings.to_ctype(t)
    
  def visit_Alloc(self, expr):
    elt_t =  expr.elt_type
    nelts = self.fresh_var("npy_intp", "nelts", self.visit_expr(expr.count))

    return "(PyArrayObject*) PyArray_SimpleNew(1, &%s, %s)" % (nelts, type_mappings.to_dtype(elt_t))
  
  
  
  def visit_Const(self, expr):
    if isinstance(expr.type, BoolT):
      return "1" if expr.value else "0"
    elif isinstance(expr.type, NoneT):
      return "0"
    return "%s" % expr.value 
  
  def visit_Var(self, expr):
    return self.name(expr.name)
  
  def visit_Cast(self, expr):
    x = self.visit_expr(expr.value)
    ct = self.to_ctype(expr.type)
    if isinstance(expr, (Const, Var)):
      return "(%s) %s" % (ct, x)
    else:
      return "((%s) (%s))" % (ct, x)
  
  
  def not_(self, x):
    if x == "1":
      return "0"
    elif x == "0":
      return "1"
    return "!%s" % x
  
  def and_(self, x, y):
    if x == "0" or y == "0":
      return "0"
    elif x == "1" and y == "1":
      return "1"
    elif x == "1":
      return y 
    elif y == "1":
      return x
    return "%s && %s" % (x,y) 
  
  def or_(self, x, y):
    if x == "1" or y == "1":
      return "1"
    elif x == "0":
      return y
    elif y == "0":
      return x 
    return "%s || %s" % (x,y) 
  
  def gt(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "0"
    return "%s > %s" % (x, y)
  
  def gte(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "1"
    return "%s >= %s" % (x,y) 
  
  def lt(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "0"
    return "%s < %s" % (x,y)
  
  def lte(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "1"
    return "%s <= %s" % (x, y) 
  
  def neq(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "0"
    return "%s != %s" % (x, y) 
  
  def eq(self, x, y, t):
    if isinstance(t, (BoolT, IntT)) and x == y:
      return "1"
    return "%s == %s" % (x, y)
  
  
  
  def visit_PrimCall(self, expr):
    t = expr.type
    args = self.visit_expr_list(expr.args)
    
    # parenthesize any compound expressions 
    for i, arg_expr in enumerate(expr.args):
      if not isinstance(arg_expr, (Var, Const)):
        args[i] = "(" + args[i] + ")"
        
    p = expr.prim 
    if p == prims.add:
      return "%s + %s" % (args[0], args[1])
    if p == prims.subtract:
      return "%s - %s" % (args[0], args[1])
    elif p == prims.multiply:
      return "%s * %s" % (args[0], args[1])
    elif p == prims.divide:
      return "%s / %s" % (args[0], args[1])
    elif p == prims.negative:
      if t == Bool:
        return "1 - %s" % args[0]
      else:
        return "-%s" % args[0]
    elif p == prims.abs:
      x  = args[0]
      return " %s >= 0 ? %s  : -%s" % (x,x,x)
    
    elif p == prims.bitwise_and:
      return "%s & %s" % (args[0], args[1])
    elif p == prims.bitwise_or:
      return "%s | %s" % (args[0], args[1])
    elif p == prims.bitwise_not:
      return "~%s" % args[0]
    
    elif p == prims.logical_and:
      return self.and_(args[0], args[1])
      
    elif p == prims.logical_or:
      return self.or_(args[0], args[1])
    
    elif p == prims.logical_not:
      return self.not_(args[0])
      
    elif p == prims.equal:
      return self.eq(args[0], args[1], t)
    
    elif p == prims.not_equal:
      return self.neq(args[0], args[1], t)
    
    elif p == prims.greater:
      return self.gt(args[0], args[1], t)
      
    elif p == prims.greater_equal:
      return self.gte(args[0], args[1], t)
    
    elif p == prims.less:
      return self.lt(args[0], args[1], t)
    
    elif p == prims.less_equal:
      return self.lte(args[0], args[1], t)
    
    elif p == prims.remainder:
      x,y = args
      if t == Float32: return "fmod(%s, %s)" % (x,y)
      elif t == Float64: return "fmod(%s, %s)" % (x,y)
      assert isinstance(t, (BoolT, IntT)), "Modulo not implemented for %s" % t
      rem = self.fresh_var(t, "rem", "%s %% %s" % (x,y))
      y_is_negative = self.fresh_var(t, "y_is_negative", "%s < 0" % y)
      rem_is_negative = self.fresh_var(t, "rem_is_negative", "%s < 0" % rem)
      y_nonzero = self.fresh_var(t, "y_nonzero", "%s != 0" % y)
      rem_nonzero = self.fresh_var(t, "rem_nonzero", "%s != 0" % rem)
      neither_zero = self.fresh_var(t, "neither_zero", "%s && %s" % (y_nonzero, rem_nonzero))
      diff_signs = self.fresh_var(t, "diff_signs", "%s ^ %s" % (y_is_negative, rem_is_negative))
      should_flip = self.fresh_var(t, "should_flip", "%s && %s" % (neither_zero, diff_signs))
      flipped_rem = self.fresh_var(t, "flipped_rem", "%s + %s" % (y, rem))
      return "%s ? %s : %s" % (should_flip, flipped_rem, rem)
    elif p == prims.fmod:
      if t == Float32: return "fmodf(%s, %s)" % (args[0], args[1])
      elif t == Float64: return "fmod(%s, %s)" % (args[0], args[1])
      return "%s %% %s" % (args[0], args[1])
    elif p == prims.maximum:
      x,y = args
      return "(%s > %s) ? %s : %s" % (x,y,x,y)
    elif p == prims.minimum:
      x,y = args
      return "(%s < %s) ? %s : %s" % (x,y,x,y)
    
    elif p == prims.power:
      if t == Float32: 
        return "powf(%s, %s)" % (args[0], args[1])
      else:
        return "pow(%s, %s)" % (args[0], args[1])
    
    elif isinstance(t, FloatT):
      # many float prims implemented using the same name in math.h
      name = p.name
      if name.startswith("arc"):
        # arccos -> acos
        name = "a" + name[3:]
      if t == Float32: name = name + "f" 
      if len(args) == 1:
        return "%s(%s)" % (name, args[0])
      else:
        assert len(args) == 2, "Unexpected prim %s with %d args (%s)" % (p, len(args), args)
        return "%s(%s, %s)" % (name, args[0], args[1])
  
    else:
      assert False, "Prim not yet implemented: %s" % p
  
  def visit_Index(self, expr):
    arr = self.visit_expr(expr.value)
    idx = self.visit_expr(expr.index)
    elt_t = expr.value.type.elt_type
    ptr_t = "%s*" % self.to_ctype(elt_t)
    return "( (%s) (PyArray_DATA(%s)))[%s]" % (ptr_t, arr, idx)
  
  def visit_Call(self, expr):
    fn_name = self.get_fn(expr.fn)
    closure_args = self.get_closure_args(expr.fn)
    args = self.visit_expr_list(expr.args)
    return "%s(%s)" % (fn_name, ", ".join(tuple(closure_args) + tuple(args)))
  
  def visit_Select(self, expr):
    cond = self.visit_expr(expr.cond)
    true = self.visit_expr(expr.true_value)
    false = self.visit_expr(expr.false_value)
    return "%s ? %s : %s" % (cond, true, false) 
  
  def is_pure(self, expr):
    return expr.__class__ in (Var, Const, PrimCall, Attribute, TupleProj, Tuple, ArrayView)
  
  def visit_Assign(self, stmt):
    rhs = self.visit_expr(stmt.rhs)

    if stmt.lhs.__class__ is Var:
      lhs = self.visit_expr(stmt.lhs)
      return "%s %s = %s;" % (self.to_ctype(stmt.lhs.type), lhs, rhs)
    elif stmt.lhs.__class__ is Tuple:
      struct_value = self.fresh_var(self.to_ctype(stmt.lhs.type), "lhs_tuple")
      self.assign(struct_value, rhs)
      
      for i, lhs_var in enumerate(stmt.lhs.elts):
        assert isinstance(lhs_var, Var), "Expected LHS variable, got %s" % lhs_var
        c_name = self.visit_expr(lhs_var)
        self.append("%s %s = %s.elt%d;" % (self.to_ctype(lhs_var.type), c_name, struct_value, i ))
      return "" 
    else:
      lhs = self.visit_expr(stmt.lhs)
      return "%s = %s;" % (lhs, rhs)
  
  def declare(self, parakeet_name, parakeet_type, init_value = None):
    c_name = self.name(parakeet_name)
    t = self.to_ctype(parakeet_type)
    if init_value is None:
      self.append("%s %s;" % (t, c_name))
    else: 
      self.append("%s %s = %s;" % (t, c_name, init_value))
  
  def declare_merge_vars(self, merge):
    """ 
    Declare but don't initialize
    """
    for (name, (left, _)) in merge.iteritems():
      self.declare(name, left.type)
      
  def visit_merge_left(self, merge, fresh_vars = True):
    
    if len(merge) == 0:
      return ""
    
    self.push()
    self.comment("Merge Phi Nodes (left side) " + str(merge))
    for (name, (left, _)) in merge.iteritems():
      c_left = self.visit_expr(left)
      if fresh_vars:
        self.declare(name, left.type, c_left)
      else:
        c_name = self.name(name)
        self.append("%s = %s;" % (c_name, c_left))
        
    return self.pop()
  
  def visit_merge_right(self, merge):
    
    if len(merge) == 0:
      return ""
    self.push()
    self.comment("Merge Phi Nodes (right side) " + str(merge))
    
    for (name, (_, right)) in merge.iteritems():
      c_right = self.visit_expr(right)
     
      self.append("%s = %s;"  % (self.name(name), c_right))
    return self.pop()
  
  def visit_If(self, stmt):
    self.declare_merge_vars(stmt.merge)
    cond = self.visit_expr(stmt.cond)
    true = self.visit_block(stmt.true) + self.visit_merge_left(stmt.merge, fresh_vars = False)
    false = self.visit_block(stmt.false) + self.visit_merge_right(stmt.merge)
    return self.indent("if(%s) {\n%s\n} else {\n%s\n}" % (cond, self.indent(true), self.indent(false))) 
  
  def visit_While(self, stmt):
    decls = self.visit_merge_left(stmt.merge, fresh_vars = True)
    cond = self.visit_expr(stmt.cond)
    body = self.visit_block(stmt.body) + self.visit_merge_right(stmt.merge)
    return decls + "while (%s) {%s}" % (cond, body)
  
  def visit_ForLoop(self, stmt):
    s = self.visit_merge_left(stmt.merge, fresh_vars = True)
    start = self.visit_expr(stmt.start)
    stop = self.visit_expr(stmt.stop)
    step = self.visit_expr(stmt.step)
    var = self.visit_expr(stmt.var)
    t = self.to_ctype(stmt.var.type)
    body =  self.visit_block(stmt.body)
    body += self.visit_merge_right(stmt.merge)
    body = self.indent("\n" + body) 
    s += "\n %(t)s %(var)s;"
    s += "\nfor (%(var)s = %(start)s; %(var)s < %(stop)s; %(var)s += %(step)s) {%(body)s}"
    return s % locals()

  def visit_Return(self, stmt):
    assert not self.return_by_ref, "Returning multiple values by ref not yet implemented: %s" % stmt
    if self.return_void:
      return "return;"
    elif isinstance(stmt.value, Tuple):
      # if not returning multiple values by reference, then make a struct for them
      field_types = get_types(stmt.value.elts) 
      struct_type = self.struct_type_from_fields(field_types)
      result_elts = ", ".join(self.visit_expr(elt) for elt in stmt.value.elts)
      result_value = "{" + result_elts + "}"
      result = self.fresh_var(struct_type, "result", result_value)
      return "return %s;" % result 
    else:
      v = self.visit_expr(stmt.value)
      return "return %s;" % v
      
  def visit_block(self, stmts, push = True):
    if push: self.push()
    for stmt in stmts:
      s = self.visit_stmt(stmt)
      self.append(s)
    self.append("\n")
    return self.indent("\n" + self.pop())
  
  def tuple_to_var_list(self, expr):
    assert isinstance(expr, Expr)
    if isinstance(expr, Tuple):
      elts = expr.elts 
    else:
      assert isinstance(expr.type, ScalarT), "Unexpected expr %s : %s" % (expr, expr.type)
      elts = [expr]
    return self.visit_expr_list(elts)
      
  
  def get_fn(self, expr):
    if expr.__class__ is  TypedFn:
      fn = expr 
    elif expr.__class__ is Closure:
      fn = expr.fn 
    else:
      assert isinstance(expr.type, (FnT, ClosureT)), \
        "Expected function or closure, got %s : %s" % (expr, expr.type)
      fn = expr.type.fn
    
    compiler = self.__class__(_tuple_struct_cache = self._tuple_struct_cache)
    compiled = compiler.compile_flat_source(fn)
    
    if compiled.sig not in self.extra_function_signatures:
      # add any declarations it depends on 
      for decl in compiled.declarations:
        self.add_decl(decl)
      
      #add any external objects it wants to be linked against 
      self.extra_objects.update(compiled.extra_objects)
      
      # first add the new function's dependencies
      for extra_sig in compiled.extra_function_signatures:
        if extra_sig not in self.extra_function_signatures:
          self.extra_function_signatures.append(extra_sig)
          extra_src = compiled.function_sources[extra_sig]
          self.extra_functions[extra_sig] = extra_src 
      # now add the function itself 
      self.extra_function_signatures.append(compiled.sig)
      self.extra_functions[compiled.sig] = compiled.src
    return compiled.name

  def get_closure_args(self, fn):
    if isinstance(fn.type, FnT):
      return []
    else:
      assert isinstance(fn, Closure), "Expected closure, got %s : %s" % (fn, fn.type)
      return self.visit_expr_list(fn.args)
      
  def build_loops(self, loop_vars, bounds, body):
    if len(loop_vars) == 0:
      return body
    var = loop_vars[0]
    bound = bounds[0]
    nested = self.build_loops(loop_vars[1:], bounds[1:], body)
    return """
    for (%s = 0; %s < %s; ++%s) {
      %s
    }""" % (var, var, bound, var, nested )
    

      
  def visit_TypedFn(self, expr):
    return self.get_fn(expr)

  def visit_UntypedFn(self, expr):
    assert False, "Unexpected UntypedFn %s in C backend, should have been specialized" % expr.name
  
  
  def return_types(self, fn):
    if isinstance(fn.return_type, TupleT):
      return fn.return_type.elt_types
    elif isinstance(fn.return_type, NoneT):
      return []
    else:
      assert isinstance(fn.return_type, (PtrT, ScalarT))
      return [fn.return_type]
    
  
  def visit_flat_fn(self, fn, return_by_ref = False):
    
    c_fn_name = self.fresh_name(fn.name)
    arg_types = [self.to_ctype(t) for t in fn.input_types]
    arg_names = [self.name(old_arg) for old_arg in fn.arg_names]
    return_types = self.return_types(fn)
    n_return = len(return_types)
    
    if n_return == 1:
      return_type = self.to_ctype(return_types[0])
      self.return_void = (return_type == NoneType)
      self.return_by_ref = False
    elif n_return == 0:
      return_type = "void"
      self.return_void = True
      self.return_by_ref = False
    elif return_by_ref:
      return_type = "void"
      self.return_void = True
      self.return_by_ref = True
      self.return_var_types = [self.to_ctype(t) for t in return_types]
      self.return_var_names = [self.fresh_name("return_value%d" % i) for i in xrange(n_return)]
      arg_types = arg_types + ["%s*" % t for t in self.return_var_types] 
      arg_names = arg_names + self.return_var_names
    else:
      return_type = self.struct_type_from_fields(return_types)
      self.return_void = False 
      self.return_by_ref = False 
    args_str = ", ".join("%s %s" % (t, name) for (t,name) in zip(arg_types,arg_names))
    
    body_str = self.visit_block(fn.body) 

    sig = "%s %s(%s)" % (return_type, c_fn_name, args_str)
    src = "%s { %s }" % (sig, body_str) 
    return c_fn_name, sig, src
  
  _flat_compile_cache = {}
  def compile_flat_source(self, parakeet_fn):
      
    # make sure compiled source uses consistent names for tuple types 
    relevant_types = set(t for t in parakeet_fn.type_env.itervalues() 
                         if isinstance(t, TupleT))
    declared_tuples = set(t for t in self._struct_type_cache.iterkeys() 
                          if t in relevant_types)
  
  
    # include your own class in the cache key so that we get distinct code 
    # for derived compilers like OpenMP and CUDA 
    key = parakeet_fn.cache_key, frozenset(declared_tuples), self.__class__
  
    if key in self._flat_compile_cache:
      return self._flat_compile_cache[key]
    name, sig, src = self.visit_flat_fn(parakeet_fn)
    result = CompiledFlatFn(name = name, 
                          sig = sig, 
                          src = src,
                          extra_objects = self.extra_objects, 
                          extra_functions = self.extra_functions,
                          extra_function_signatures = self.extra_function_signatures,
                          declarations = self.declarations)
    self._flat_compile_cache[key] = result
    return result
