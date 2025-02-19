#include <klee/klee.h>
#include <stdio.h>

#define N 6
#define BOUND 9
#define DELAY 2
int pc[N] = {0}, lock = -1, tick = 0, savetick[N] = {0};

void search();
void check_mutual_exclusion(int);

main() { search(0); }

void search(int level) { 
    printf("Search(%d): tick = %d\n", level, tick);
    if (level > BOUND) return;
    int id;
    __CPROVER_assume(id >= 0 && id <= N-1);
    //klee_range(0, N - 1, "id");
    switch (pc[id]) {
       case 0: if (lock == -1) { pc[id] = 1; search(level+1);  } break;
       case 1: lock = id; savetick[id] = tick++; pc[id] = 2; search(level+1); break; 
       case 2: if (tick > savetick[id] + DELAY) { pc[id] = 3; search(level+1); } break;
       case 3: if (lock == id) { check_mutual_exclusion(id); lock = -1; pc[id] = 0; search(level+1);  } break;
    }
    printf("Return level %d\n", level);
}

void check_mutual_exclusion(int id) {
    for (int i = 0; i < N; i++) {
        if (i == id) printf("Critical id %d tick %d\n", i, tick);
        if (i != id && pc[i] == 3) exit(0);
    }
}

/***
int choice(k) {
    if (!k) return 0;
    if (*) return k; else return choice(k - 1);
}

int choice() {
  int c, z = -1;
  c = klee_range(0, N - 1, "c");
  for(int i = 0; i <= c; i++) z = i;
  if (z == -1) exit(0);
  return z;
}

/***
Process i: one step
    repeat
        await(lock = 0); // no blocking: this is while (lock != 0) skip;
        lock := i
        delay 
    until(lock = i);
    critical section; 
    lock := 0;



---------------------------------------------------------------------------
|    Path    |  Instrs|  Time(s)|  ICov(%)|  BCov(%)|  ICount|  TSolver(%)|
---------------------------------------------------------------------------
|fischer.klee|   17499|    45.86|    35.88|    21.25|     379|       99.85|
---------------------------------------------------------------------------

-------------------------------------------------------------------------
|   Path   |  Instrs|  Time(s)|  ICov(%)|  BCov(%)|  ICount|  TSolver(%)|
-------------------------------------------------------------------------
|fischer.tx|    8987|    29.69|    35.62|    20.00|     379|       99.53|
-------------------------------------------------------------------------


***/
