import numpy as np 
import parakeet as par 
from testing_helpers import run_local_tests, expect_each 

ints_1d = np.arange(100, dtype='int')
floats_1d = np.arange(100, dtype='float')
ints_2d = np.reshape(ints_1d, (10,10))
floats_2d = np.reshape(ints_2d, (10,10))
bools_1d = ints_1d % 2 == 0
bools_2d = ints_2d % 2 == 0

all_arrays = [ints_1d, ints_2d, floats_1d, floats_2d, bools_1d, bools_2d]

def add1_scalar(x):
  return x+1

def test_add1_external_map():
  assert par.map(add1_scalar, [1,2,3]) == np.array([2,3,4])

def add1_map(x_vec):
  return par.map(add1_scalar, x_vec)

def test_add1_internal_map():
  expect_each(add1_map, add1_scalar, all_arrays)
  
if __name__ == '__main__':
  run_local_tests()