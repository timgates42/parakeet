import itertools 
import numpy as np
import types


from frontend import ast_conversion
from ndtypes import ScalarT, StructT, Type, type_conv     
from syntax import (Expr, Var, Tuple, 
                    UntypedFn, TypedFn, 
                    Return, If, While, ForLoop, ParFor, ExprStmt,   
                    ActualArgs, 
                    Assign, Index, AllocArray,)
from parakeet.frontend import ast_conversion

class ReturnValue(Exception):
  def __init__(self, value):
    self.value = value

class ClosureVal:
  def __init__(self, fn, fixed_args):
    self.fn = fn
    self.fixed_args = tuple(fixed_args)

  def __call__(self, args):
    if isinstance(args, ActualArgs):
      args = args.prepend_positional(self.fixed_args)
    else:
      args = self.fixed_args + tuple(args)
    return eval_fn(self.fn, args)

def eval(fn, actuals):
  result = eval_fn(fn, actuals)
  import ctypes 
  if isinstance(result, ctypes.Structure):
    return type_conv.to_python(result, fn.return_type)
  return result 
   
def eval_fn(fn, actuals):

  if isinstance(fn, np.dtype):
    return fn.type(*actuals)
  elif isinstance(fn, TypedFn):
    assert len(fn.arg_names) == len(actuals), \
      "Wrong number of args, expected %s but given %s" % \
      (fn.arg_names, actuals)
    env = {}

    for (k,v) in zip(fn.arg_names, actuals):
      env[k] = v
  elif isinstance(fn, UntypedFn):
    # untyped functions have a more complicated args object
    # which deals with named args, variable arity, etc..
    env = fn.args.bind(actuals)
  elif isinstance(fn, ClosureVal):
    return fn(actuals)
  else:
    return fn(*actuals)

  def eval_args(args):
    if isinstance(args, (list, tuple)):
      return map(eval_expr, args)
    else:
      return args.transform(eval_expr)

  def eval_if_expr(maybe_expr):
    return eval_expr(maybe_expr) if isinstance(maybe_expr, Expr) else maybe_expr
  
  def eval_expr(expr):

    if hasattr(expr, 'wrapper'):
      expr = expr.wrapper
    assert isinstance(expr, Expr), "Not an expression-- %s : %s" % \
         (expr, type(expr))
         
    def expr_Const():
      return expr.value

    def expr_Attribute():
      value = eval_expr(expr.value)
      if expr.name == 'offset':
        if value.base is None:
          return 0
        else:
          return value.ctypes.data - value.base.ctypes.data
      elif isinstance(value, tuple):
        if expr.name.startswith('elt'):
          field = int(expr.name[3:])
        else:
          field = int(expr.name)
        return value[field]  
      else:
        return getattr(value, expr.name)

    def expr_Alloc():
      count = eval_expr(expr.count)
      arr = np.empty(shape = (count,), dtype = expr.elt_type.dtype)
      return arr
      
    def expr_AllocArray():
      shape = eval_expr(expr.shape)
      assert isinstance(shape, tuple), "Expected tuple, got %s" % (shape,)
      assert isinstance(expr.elt_type, ScalarT), \
          "Expected scalar element type for AllocArray, got %s" % (expr.elt_type,)
      dtype = expr.elt_type.dtype
      return  np.ndarray(shape = shape, dtype = dtype) 
    
    def expr_ArrayView():
      data = eval_expr(expr.data)
      shape  = eval_expr(expr.shape)
      strides = eval_expr(expr.strides)
      offset = eval_expr(expr.offset)
      dtype = expr.type.elt_type.dtype
      if isinstance(data, np.ndarray):
        data = data.data 
      bytes_per_elt = dtype.itemsize
      return np.ndarray(shape = shape, 
                        offset = offset, 
                        buffer = data, 
                        strides = tuple(si * bytes_per_elt for si in  strides), 
                        dtype = np.dtype(dtype))
      
      
    def expr_Array():
      elt_values = map(eval_expr, expr.elts)
      return np.array(elt_values)

    def expr_Index():
      array = eval_expr(expr.value)
      index = eval_expr(expr.index)
      return array[index]

    def expr_PrimCall():

      return expr.prim.fn (*eval_args(expr.args))
    
    def expr_Slice():
      return slice(eval_expr(expr.start), eval_expr(expr.stop),
                   eval_expr(expr.step))

    def expr_Var():
      return env[expr.name]

    def expr_Call():
      fn = eval_expr(expr.fn)
      arg_values = eval_args(expr.args)
      return eval_fn(fn, arg_values)

    def expr_Closure():
      if isinstance(expr.fn, (UntypedFn, TypedFn)):
        fundef = expr.fn
      else:
        assert isinstance(expr.fn, str)
        fundef = UntypedFn.registry[expr.fn]
      closure_arg_vals = map(eval_expr, expr.args)
      return ClosureVal(fundef, closure_arg_vals)

    def expr_Fn():
      return ClosureVal(expr, [])

    def expr_TypedFn():
      return ClosureVal(expr, [])

    def expr_Cast():
      x = eval_expr(expr.value)
      t = expr.type
      assert isinstance(t, ScalarT)
      # use numpy's conversion function
      return t.dtype.type(x)
    
    def expr_Select():
      cond = eval_expr(expr.cond)
      trueval = eval_expr(expr.true_value)
      falseval = eval_expr(expr.false_value)
      return trueval if cond else falseval 

    def expr_Struct():
      assert expr.type, "Expected type on %s!" % expr
      assert isinstance(expr.type, StructT), \
          "Expected %s : %s to be a struct" % (expr, expr.type)
      elts = map(eval_expr, expr.args)
      return expr.type.ctypes_repr(*elts)

    def expr_Tuple():
      return tuple(map(eval_expr, expr.elts))
    
    def expr_TupleProj():
      return eval_expr(expr.tuple)[expr.index]

    def expr_ClosureElt():
      assert isinstance(expr.closure, Expr), \
          "Invalid closure expression-- %s : %s" % \
          (expr.closure, type(expr.closure))
      clos = eval_expr(expr.closure)
      return clos.fixed_args[expr.index]

    def expr_Range():
      return np.arange(eval_expr(expr.start), eval_expr(expr.stop), eval_expr(expr.step))
    
    def expr_Len():
      return len(eval_expr(expr.value))
    
    def expr_IndexMap():
      fn = eval_expr(expr.fn)
      shape = eval_expr(expr.shape)
      dtype = expr.type.elt_type.dtype
      result = np.empty(shape, dtype = dtype)
      for idx in np.ndindex(shape):
        result[idx] = eval_fn(fn, (idx,))
      return result
      
    def expr_IndexReduce():
      fn = eval_expr(expr.fn)
      combine = eval_expr(expr.combine)
      shape = eval_expr(expr.shape)
      if not isinstance(shape, (list, tuple) ):
        shape = [shape]
      ranges = [xrange(n) for n in shape]
      
      acc = eval_if_expr(expr.init)
      for idx in itertools.product(*ranges):
        if len(idx) == 1:
          idx = idx[0]
        elt = eval_fn(fn, (idx,))
        if acc is None:
          acc = elt 
        else:
          elt = eval_fn(combine, (acc, elt))
      return elt 
    
    fn_name = "expr_" + expr.__class__.__name__
    dispatch_fn = locals()[fn_name]
    result = dispatch_fn()
    
    # we don't support python function's inside parakeet,
    # they have to be translated into Parakeet functions
    if isinstance(result, types.FunctionType):
      fundef = ast_conversion.translate_function_value(result)
      return ClosureVal(fundef, fundef.python_nonlocals())
    else:
      return result

  def eval_merge_left(phi_nodes):
    for result, (left, _) in phi_nodes.iteritems():
      env[result] = eval_expr(left)

  def eval_merge_right(phi_nodes):
    for result, (_, right) in phi_nodes.iteritems():
      env[result] = eval_expr(right)

  def assign(lhs, rhs, env):
    if isinstance(lhs, Var):
      env[lhs.name] = rhs
    elif isinstance(lhs, Tuple):
      assert isinstance(rhs, tuple)
      for (elt, v) in zip(lhs.elts, rhs):
        assign(elt, v, env)
    elif isinstance(lhs, Index):
      arr = eval_expr(lhs.value)
      idx = eval_expr(lhs.index)
      arr[idx] = rhs

  

  def eval_parfor_seq(fn, bounds):
    if isinstance(bounds, (list,tuple)) and len(bounds) == 1:
      bounds = bounds[0]
        
    if isinstance(bounds, (int, long)):
      for idx in xrange(bounds):
        eval_fn(fn, (idx,))
    else:
      for idx in np.ndindex(bounds):
        eval_fn(fn, (idx,))
  
    
  def eval_parfor_shiver(clos, bounds):
    assert hasattr(clos, "__call__"), "Unexpected fn %s" % (clos,) 
    assert isinstance(bounds, (int,long,tuple)), "Invalid bounds %s" % (bounds,)
    
    if isinstance(clos, ClosureVal):
      fn = clos.fn
      fixed_args = clos.fixed_args 
    else:
      fn = clos 
      fixed_args = ()
    
    
    if isinstance(bounds, (tuple,list)) and len(bounds) == 1:
      bounds = bounds[0]
    
    
    full_args = tuple(fixed_args) + (bounds,)
    
    if isinstance(fn, TypedFn):
      typed = fn
      linear_args = fixed_args  
    else:
      from frontend import specialize 
      typed, linear_args = specialize(fn, full_args)
    
    import transforms,  llvm_backend
    from llvm_backend import ctypes_to_generic_value
    lowered_fn = transforms.pipeline.lowering(fn)
    llvm_fn = llvm_backend.compile_fn(lowered_fn).llvm_fn 
    
    expected_types = typed.input_types[:-1]
    
    ctypes_inputs = [t.from_python(v) 
                     for (v,t) 
                     in zip(linear_args, expected_types)]
    
    gv_inputs = [ctypes_to_generic_value(cv, t) 
                 for (cv,t) 
                 in zip(ctypes_inputs, expected_types)]
    
    import shiver 
    shiver.parfor(llvm_fn, bounds, 
                  fixed_args = gv_inputs, 
                  ee = llvm_backend.global_context.exec_engine)  
  def eval_stmt(stmt):
    if isinstance(stmt, Return):
      v = eval_expr(stmt.value)
      raise ReturnValue(v)
    
    elif isinstance(stmt, Assign):
      value = eval_expr(stmt.rhs)
      assign(stmt.lhs, value, env)

    elif isinstance(stmt, If):
      cond_val = eval_expr(stmt.cond)
      if cond_val:
        eval_block(stmt.true)
        eval_merge_left(stmt.merge)
      else:
        eval_block(stmt.false)
        eval_merge_right(stmt.merge)

    elif isinstance(stmt, While):
      eval_merge_left(stmt.merge)
      while eval_expr(stmt.cond):
        eval_block(stmt.body)
        eval_merge_right(stmt.merge)
        
    elif isinstance(stmt, ForLoop):
      start = eval_expr(stmt.start)
      stop = eval_expr(stmt.stop)
      step = eval_expr(stmt.step)
      eval_merge_left(stmt.merge)
      for i in xrange(start, stop, step):
        env[stmt.var.name] = i
        eval_block(stmt.body)
        eval_merge_right(stmt.merge)
      
        
    elif isinstance(stmt, ExprStmt):
      eval_expr(stmt.value)
      
    elif isinstance(stmt, ParFor):
      fn = eval_expr(stmt.fn)
      bounds = eval_expr(stmt.bounds)
    
      eval_parfor_seq(fn, bounds)    
      
      
    else:
      raise RuntimeError("Statement not implemented: %s" % stmt)

  def eval_block(stmts):
    for stmt in stmts:
      eval_stmt(stmt)

  try:
   
    eval_block(fn.body)

  except ReturnValue as r:
    return r.value 
  except:
    raise

def run_python_fn(python_fn, args, kwds):
  untyped  = ast_conversion.translate_function_value(python_fn)
  # should eventually roll this up into something cleaner, since
  # top-level functions are really acting like closures over their
  # global dependencies
  global_args = [python_fn.func_globals[n] for n in untyped.nonlocals]
  all_positional = global_args + list(args)
  actuals = args.FormalArgs(all_positional, kwds)
  return eval_fn(untyped, actuals)
