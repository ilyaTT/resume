
/*
 * Данная реализация предполагает, что ограничения будут: нижнее = 0, верхнее - положительное число
 * Для доп. логики нужно обработать случай с r_artificial, а так же в solve_simplex добавить обработку для фазы 2
 *
 * */

#include "time.h"
#include "Python.h"
#include "numpy/arrayobject.h"

void printT(double **T, size_t x, size_t y){
	size_t i, j;

	printf("\n");
    for(i=0; i<y; i++) {
        for (j=0; j<x; j++) {
            printf("%10.2f", T[i][j]);
        }
        printf("\n");
    }
    printf("\n");
}

//#define checkpoint fprintf(stderr, "FUNC: %-21s LINE: %4d MARK\n", __FUNCTION__, __LINE__); //printT(T, x, y);
#define checkpoint


//#define _START _start = clock();
//#define _DELTA(_label) _label += ((float)(clock() - _start) / 1000000.0F ) * 1000;
//#define _VIEW(_label) printf(#_label ": %f\n", _label);

#define _START
#define _DELTA(_label)
#define _VIEW(_label)



// решатель симплекс метода
int solve_simplex(double **T, size_t x, size_t y, int *basis, size_t basis_size, size_t maxiter, int phase, double tol, int *p_nit, char bland){
	// флаг готовности расчета
	char complete = 0;
	// получаем значение итераций
	int nit = *p_nit;
	size_t u, w, i, j;
	int pivcol, pivrow;
	double a, b, pivval, i_pivval, div_res, a_b_div, search_pivcol;
	int k, status = 10;
	double *row_tmp, *row_pivrow;


	clock_t _start, _end;
	float _t1=0, _t2=0, _t3=0, _t4=0;


	// смещение среза столбца
	k = phase == 1 ? 2 : 1;

	// строка поиска pivcol
	u = y - 1;
	// одна из колонок поиска pivrow
	w = x - 1;

	if(phase == 2){
		for(pivrow=0; pivrow<basis_size; pivrow++){
			if(basis[pivrow] <= x-2){
				continue;
			}
			for(pivcol=0; pivcol<x-1; pivcol++){
				if(T[pivrow, pivcol] != 0){
					// отмечаем pivcol в basis
					basis[pivrow] = pivcol;
					// находим значение piv
					pivval = T[pivrow][pivcol];
					// вычисляем новый pivrow
					for(j=0; j<x; j++){
						T[pivrow][j] /= pivval;
					}
					// пересчитываем все строки исходя из pivrow и pivcol
					for(i=0; i<y; i++){
						// значение контрольной ячейки в строке
						i_pivval = T[i][pivcol];
						// имеет смысл, если она не равна нулю
						if(i != pivrow && i_pivval != 0){
							for(j=0; j<x; j++){
								T[i][j] -= T[pivrow][j] * i_pivval;
							}
						}
					}
					// увеличиваем счетчик итераций
					nit++;
					break;
				}
			}
		}
	}

	checkpoint

	// цикл решения
	for(;;){
		// для каждой итерации - заново выставляем инициализационные значения
		pivcol = -1;
		pivrow = -1;
		search_pivcol = 1.0e+10;
		a_b_div = 1.0e+10;

		// проверка превышения лимита итераций
		if(nit >= maxiter){
			status = 1;
			break;
		}

		row_tmp = T[u];

		_START
		// ищем pivcol
		for(j=0; j<x-1; j++){
			// пропускаем все, что больше отрицательного предела
			if((a = row_tmp[j]) >= -tol){
				continue;
			}
			// только если он меньше, чем ранее расчитанный - сохраняем его и pivrow
			if(a < search_pivcol){
				pivcol = j;
				search_pivcol = a;
				// если указан более тщательный алгоритм поиска - прекращаем тут
				if(bland){
					break;
				}
			}
		}
		// если не найден - решено
		if(pivcol == -1){
			status = 0;
			break;
		}
		_DELTA(_t1);

		//printf("pivcol: %i\n", pivcol);

		_START
		// ищем pivrow
		for(i=0; i<y-k; i++){
			row_tmp = T[i];

			// если одно из значений не подходит - деление не имеет смысла
			if((a = row_tmp[pivcol]) <= tol){
				continue;
			}
			b = row_tmp[w];
			// получаем результат деления
			div_res = b / a;
			// только если он меньше, чем ранее расчитанный - сохраняем его и pivrow
			if(div_res < a_b_div){
				a_b_div = div_res;
				pivrow = i;
			}
		}
		// если не найден - ошибка
		if(pivrow == -1){
			status = 3;
			break;
		}
		_DELTA(_t2);

		row_pivrow = T[pivrow];

		//printf("pivrow: %i\n", pivrow);

		// отмечаем pivcol в basis
		basis[pivrow] = pivcol;
		// находим значение piv
		pivval = row_pivrow[pivcol];
		// вычисляем новый pivrow
		_START
		for(j=0; j<x; j++){
			row_pivrow[j] /= pivval;
		}
		_DELTA(_t3);

		// пересчитываем все строки исходя из pivrow и pivcol
		_START
		for(i=0; i<y; i++){
			row_tmp = T[i];
			// значение контрольной ячейки в строке
			i_pivval = row_tmp[pivcol];
			// имеет смысл, если она не равна нулю
			if(i != pivrow && i_pivval != 0){
				for(j=0; j<x; j++){
					if(row_pivrow[j] != 0){
						row_tmp[j] -= row_pivrow[j] * i_pivval;
					}
				}
			}
		}
		_DELTA(_t4);
		// увеличиваем счетчик итераций
		nit++;
	}

	_VIEW(_t1);
	_VIEW(_t2);
	_VIEW(_t3);
	_VIEW(_t4);

	// сохраняем значение счетчика
	*p_nit = nit;

	return status;
}


PyObject *py_linprog(PyObject *self, PyObject *args, PyObject *kwargs){
    // параметры
    static char *kw_params[] = {"c", "A_ub", "b_ub", "A_eq", "b_eq", "maxiter", "tol", "bland", "p0", NULL};

    PyObject *cc = NULL;
    PyObject *A_ub = NULL;
    PyObject *b_ub = NULL;
    PyObject *A_eq = NULL;
    PyObject *b_eq = NULL;
    size_t maxiter = 10000;
    double tol = 1.0e-10;
    char bland = 0;
    double p0 = 0;
    int avcount = 0;
	int	slcount = 0;
	int status;
	int nit = 0;

    size_t n, mub, meq, m, n_slack, n_artificial, x, y, u, w, i, j, n_solution;

    // собственно основной 2-d массив
    double **T, *p, *solution = NULL;
    // вспомогательные 1-d массивы
    int *basis, *r_artificial;

    // словарь ответа
    PyObject *py_response, *py_solution, *py_float;

	// производим разбор аргументов
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O!O!O!O!O!|IdBd:linprog", kw_params,
    		&PyArray_Type, &cc,
    		&PyArray_Type, &A_ub,
    		&PyArray_Type, &b_ub,
    		&PyArray_Type, &A_eq,
    		&PyArray_Type, &b_eq,
    		&maxiter,
    		&tol,
    		&bland,
    		&p0
    	)) {
		return NULL;
    }

    checkpoint

    // определяем размерность данных
    n = PyArray_SIZE(cc);
	// The number of upper bound constraints (rows in A_ub and elements in b_ub)
	mub = PyArray_SIZE(b_ub);
	// The number of equality constraints (rows in A_eq and elements in b_eq)
	meq = PyArray_SIZE(b_eq);
	// The total number of constraints
	m = mub + meq;
	// The number of slack variables (one for each of the upper-bound constraints)
	n_slack = mub;
	// The number of artificial variables (one for each lower-bound and equality constraint)
	n_artificial = meq;
	// размерность списка решения
	n_solution = n + n_slack + n_artificial;

	// размерности основной матрицы
	x = n+n_slack+n_artificial+1;
	y = m+2;

	checkpoint

	//printf("START SIZE: %i, %i\n", y, x);

	// создаем основную матрицу
	T = (double**)calloc(y, sizeof(double*));
	for(i=0; i<y; i++){
		T[i] = (double*)calloc(x, sizeof(double));
	}

	checkpoint

	// начинаем писать в нее данные
	u = y - 2;
	for(j=0; j<n; j++){
		T[u][j] = *((double *)PyArray_GETPTR1(cc, j));
	}
	T[u][x-1] = p0;

	checkpoint

	// копируем A_eq
	for(i=0; i<meq; i++){
		for(j=0; j<n; j++){
			T[i][j] = *((double *)PyArray_GETPTR2(A_eq, i, j));
		}
	}

	checkpoint

	// копируем b_eq
	w = x - 1;
	for(i=0; i<meq; i++){
		T[i][w] = *((double *)PyArray_GETPTR1(b_eq, i));
	}

	// копируем A_ub
	for(i=meq; i<m; i++){
		for(j=0; j<n; j++){
			T[i][j] = *((double *)PyArray_GETPTR2(A_ub, i-meq, j));
		}
	}

	checkpoint

	// копируем b_ub
	w = x - 1;
	for(i=meq; i<m; i++){
		T[i][w] = *((double *)PyArray_GETPTR1(b_ub, i-meq));
	}

	// заполнение левого нижнего прямоугольника по диагонали единицами
	for(i=meq, j=n; i<m || j<n+n_slack; i++, j++){
		T[i][j] = 1;
	}

	checkpoint

	// создаем вспомогательные массивы
    basis = (int*)calloc(m, sizeof(int));
    r_artificial = (int*)calloc(n_artificial, sizeof(int));

    // заполняем вспомогательные матрицы
    u = y - 1;
	for(i=0; i<meq; i++){
		basis[i] = n + n_slack + avcount;
		r_artificial[avcount] = i;
		avcount++;
        T[i][basis[i]] = 1;
        T[u][basis[i]] = 1;
	}
	for(i=meq; i<m; i++){
        basis[i] = n + slcount;
        slcount++;
	}

	//  T[-1, :] = T[-1, :] - T[r, :]
	u = y - 1;
	for(i=0; i<n_artificial; i++){
		for(j=0; j<x; j++){
			T[u][j] -= T[i][j];
		}
	}

	checkpoint

	//printT(T, x, y);

	// выполняем первичное решение симплекс-метода
    status = solve_simplex(T, x, y, basis, m, maxiter, 1, tol, &nit, bland);

	checkpoint

	// проверяем, корректно ли решился этап
	if(fabs(T[y-1][x-1]) >= tol){
		status = 2;
		goto end;
	}

	// убираем последнюю строку
	free(T[y-1]);
	y--;

	// убираем artificial из всех строк
	for(i=0; i<y; i++){
		// создаем новый буфер без artificial
		p = (double*)calloc(x-n_artificial, sizeof(double));
		// копируем туда две первые основные части
		memcpy(p, T[i], sizeof(double)*(n + n_slack));
		// копируем последнюю колонку
		p[n + n_slack] = T[i][x-1];
		// освобождаем старый буфер
		free(T[i]);
		// присваиваем новый буфер
		T[i] = p;
	}
	// уменьшаем размерность x
	x -= n_artificial;

	checkpoint

	// выполняем вторичное решение симплекс-метода
    status = solve_simplex(T, x, y, basis, m, maxiter-nit, 2, tol, &nit, bland);

	// вектор решения
	solution = (double*)calloc(n_solution, sizeof(double));
	// пишем решенные значения
	for(i=0; i<m; i++){
		solution[basis[i]] = T[i][x-1];
	}

end:
	// если завершение некорректное - решения нет
	if(status != 0){
		n_solution = 0;
	}

	// собираем питоновский результирующий список
	py_solution = PyList_New(n_solution);
	for (i=0; i<n_solution; i++) {
	    PyList_SET_ITEM(py_solution, i, PyFloat_FromDouble(solution[i]));   // reference to num stolen
	}

	// собираем результат
	py_response = PyDict_New();
    PyDict_SetItem(py_response, Py_BuildValue("s", "status"), Py_BuildValue("i", status));
    PyDict_SetItem(py_response, Py_BuildValue("s", "nit"), Py_BuildValue("i", nit));
    PyDict_SetItem(py_response, Py_BuildValue("s", "solution"), py_solution);
    PyDict_SetItem(py_response, Py_BuildValue("s", "fun"), Py_BuildValue("d", -T[y-1][x-1]));

	// освобождение памяти
	for(i=0; i<y; i++){
		free(T[i]);
	}
	free(T);
	free(basis);
	free(r_artificial);
	free(solution);

    return py_response;
}

static PyMethodDef linprog_methods[] = {
    { "solve", (PyCFunction)py_linprog, METH_VARARGS | METH_KEYWORDS, "Calculate linprog function" },
    { NULL }
};

void init_linprog(void) {
	PyObject *mod;
	mod = Py_InitModule("_linprog", linprog_methods);
	import_array();
}

