from netCDF4           import Dataset
from json              import loads
from scipy.integrate   import simps
from scipy.signal      import csd
from scipy.io          import savemat
from numpy             import tile, copy, ndim, shape, arange, roll, sqrt, conjugate
from numpy             import correlate, average, empty, array_equal, squeeze, transpose
from numpy             import gradient, angle, absolute, sum, ndarray, pi, log, gradient
from matplotlib.pyplot import pcolormesh, show, plot, colorbar, title, savefig
from scipy.constants   import e, m_e, m_p, m_n

## CONSTANTS
m_i   = m_p + m_n
T_old = 25; R_old = 1.65; B_old = 1.9
alpha_old = 0.000274
constant  = alpha_old * (R_old **  2) * (T_old ** (-5/2)) * B_old


class Analyse ():
    '''
    Class to open and analyse the output data from the 2D FELTOR simulations
    to run it one must introduce the name of the output File
    '''

    def __init__ (self, File_name, Access_Mode = 'r', input_model = False, dimensions = False, fields = False, get_everything = True, integrate_fields = False, crop = 1, parallel = False):
        '''
        Open the data and extract some important parameters
        Also calculate the Center of Mass
        '''
        self.Data  = Dataset(File_name, Access_Mode, format="NETCDF4", parallel = parallel)
        if input_model or get_everything:
            self.input = loads(self.Data.inputfile)
            self.find_model()

        if dimensions or get_everything:
            self.Nx   = self.input['n_out'] * self.input['Nx_out']
            self.Ny   = self.input['n_out'] * self.input['Ny_out']
            self.time = copy(self.Data['time'][:])
            self.nt   = len(self.time)
            if self.nt < 2:
                raise ValueError('The field contains only the initial conditions')


            self.x,  self.y  = copy(self.Data['x'][:]), copy(self.Data['y'][:])
            self.lx, self.ly = self.input['lx'],        self.input['ly']
            self.dt  = (self.time[-1] - self.time[0]) / self.nt

        if fields or get_everything:
            nb, sign = (0, -1) if 'complete' not in File_name.lower() else (self.input['nb'], 1)
            self.ions      = copy(self.Data['ions'][::crop]).transpose((0, 2, 1)) + nb
            self.potential = sign * copy(self.Data['potential'][::crop]).transpose((0, 2, 1))
            self.v_r       = -gradient(self.potential, self.y, axis = 2)
            self.vorticity = copy(self.Data['vorticity'][::crop]).transpose((0, 2, 1))

        if (dimensions and fields and integrate_fields) or get_everything:
            self.Mass      = self.integrate(self.ions, crop = crop) / (self.lx * self.ly)
            self.Potential = self.integrate(self.potential, crop = crop) / (self.lx * self.ly)

    def find_model(self):
        '''
        A function to get the name of the model. The FELTOR simulator gets different
        names than the ones used to call them. This is caused because to use the
        HW modified, we use the variable modified=1. For that reason, we need to
        "translate" the name. I.e. model='HW' & modified=0 ==> 'HW_ord'
        '''
        self.model = self.input['model']
        if 'HW' in self.model:
            model = self.model
            md_ln = len(model)
            pos   = model.find('HW')
            if self.input['modified']:
                self.model = model[:pos + 2] + '_mod'
            else:
                self.model = model[:pos + 2] + '_ord'
            if pos + 2 < len(model):
                self.model += model[pos + 2:]

    def CM(self):
        '''
        Function to calculate the Center of Mass of the system for all the time steps
        The Center of Mass is a 2D vector, for that reason we obtain 2 coordinate, X and Y,
        separately
        '''

        X_mat = tile(self.x.reshape(self.Nx, 1), self.Ny)
        Y_mat = tile(self.y.reshape(self.Ny, 1), self.Nx).transpose()

        self.X_CM = self.integrate(X_mat * self.ions) / (self.lx * self.ly * self.Mass)
        self.Y_CM = self.integrate(Y_mat * self.ions) / (self.lx * self.ly * self.Mass)

    def V_CM(self):
        '''
        Function to calculate the velocity of the Center of Mass of the system
        for all the time steps
        The velocidty of the Center of Mass is a 2D vector, for that reason we
        obtain 2 coordinate, X and Y, separately.
        In this case it is calculated as grad(X, time), using the numpy gradient
        function, which uses V = (x_i+1 - x_i-1) / (t_i+1 - t_i-1) for every value
        except the boundaries, which uses V = (x_i - x_i-1) / (t_i - t_i-1).
        '''

        self.V_CM_x = gradient(self.X_CM, self.time)
        self.V_CM_y = gradient(self.Y_CM, self.time)

    def integrate(self, variable, dim_integral = 2, axis = -1, typ = 't', indep_vars = None, crop = 1):
        '''
        Function to integrate a variable over the grid, this variable could be
        a vector or a matrix, or over time (would be better to average over time)
        The integral can only be made in 1 or 2 dimensons, starting at dimension 0 or -1
        in case we want to integrate in 2 dimensions.
        It is important to notice that the indep_vars variable is only for when
        we want to integrate a tensor with non conventional dimensions.
        '''

        if type(variable) == str:
            Integral = copy(self.Data[variable][::crop].transpose((0, 2, 1)))
        else:
            Integral = copy(variable[::crop])

        dim_var = ndim(Integral)

        if type(indep_vars) != type(None):
            pass
        elif dim_var == 3:
            indep_vars = [self.time, self.x, self.y]
        elif dim_var == 2:
            indep_vars = [self.x, self.y]
        else:
            indep_vars = [self.time] if typ == 't' else [self.y] if typ == 'y' else [self.x]

        if dim_var >= 2 and dim_integral == 2:
            Integral  = simps(Integral, indep_vars[axis], axis = axis)
            axis_vars = 1 if axis == 0 else -2
            Integral  = simps(Integral, indep_vars[axis_vars], axis = axis)

        else:
            if dim_var == 1:
                axis  = 0
            Integral = simps(Integral, indep_vars[axis], axis = axis)

        return Integral

    def pcolormesh_variable(self, variable_name, time_step, set_color_bar = False, save = None, **kwargs):
        '''
        Easy function to plot 2D variables such ions or vorticity
        '''

        if type(variable) == str:
            parameter = copy(self.Data[variable][time_step])
        else:
            parameter = copy(variable).transpose((0, 2, 1))

        pcolormesh(self.x, self.y, parameter, **kwargs)
        if set_color_bar:
            colorbar()
        if save != None and type(save) == str:
            savefig(save)
        show();

    def plot_parameter(self, variable, x = None, save = None, **kwargs):
        '''
        Easy function to plot time dependance scalar variables such CM or the total Mass
        '''
        if type(variable) == str:
            parameter = copy(self.Data[variable][time_step])
        else:
            parameter = copy(variable)

        if ndim(parameter) != 1:
            raise ValueError('The dimension of the variable are different than 1, try to use imshow.')

        if type(x) == type(None):
            if len(parameter) == self.tm_stps:
                x = self.time
            else:
                x = arange(len(parameter))

        plot(x, parameter, **kwargs)

        if save != None and type(save) == str:
            savefig(save)
        show();


    def c_corr_dt (self, f, g, time_units = 1):
        '''
        Cross-correlation time-delay. It is inspired in the discrete correlation
        But as we only need to look at a correlation for a tiny time shift, time_units,
        it does it with for loops. It is important to take into account that the lack
        of an infinite amount of values would make values decrease as they approach
        the borders. For that reason, the function always take the same amount of values.
        '''

        assert array_equal(shape(f), shape(g)), 'The dimensions of f and g should be equal'

        ## + 1 because we wanna do [-time_units, time_units]
        steps  = int(time_units / self.dt) + 1
        corr   = empty((2 * steps + 1, self.Nx, self.Ny))
        nt     = len(f)
        g_conj = conjugate(g)

        corr  = empty((2 * steps + 1, self.Nx, self.Ny))
        for i in range(-steps, steps + 1):
            corr[steps + i,:,:] = average((f * roll(g_conj,i,axis=0))[steps:-steps],axis=0)

        corr = self.integrate(corr, 1, axis = -1) / self.ly

        return corr



    def c_corr_sp (self, f, g, x0=None, y0=None, integrate = False):
        '''
        Spatial cross-correlation, x and y should not be integrated. In this case,
        we avoid using the numpy and scipy functions for correlation, as they padd the
        signal with 0s, but we have a periodic signal.
        '''

        assert array_equal(shape(f), shape(g)), 'The dimensions of f and g should be equal'


        if type(x0) != type(None) and type(y0) == type(None):
            z, axis        = x0, 0
            f_cp, g_cp     = copy(f[:, z, :]), conjugate(g[:, z, :])
            transpose_back = False

        elif type(x0) == type(None) and type(y0) != type(None):
            z, axis        = y0, 1
            f_cp, g_cp     = transpose(f, (0,2,1))[:,z,:], conjugate(transpose(g, (0,2,1))[:,z,:])
            transpose_back = True

        else:
            raise TypeError('One of the variables should be None, the other and int optimizer an array of ints')

        if type(z) == list or type(z) == ndarray:
            nt, mz, ny = shape(f_cp)
        else:
            mz = 1
            nt, ny = shape(f_cp)


        steps = int(ny / 2)
        fcg = empty((nt, mz, 2 * steps + 1)).squeeze()

        for i in range(-steps, steps + 1):
            fcg[:,..., steps + i] = self.integrate((f_cp * roll(g_cp,i,axis=-1))
                                                   ,1,axis=-1)

        fcg /= [self.lx, self.ly][axis - 1]

        fcg = average(fcg, axis = 0)

        if transpose_back:
            fcg = transpose(fcg, (0, 2, 1))

        if integrate:
            fcg = self.integrate(fcg, axis = axis) / [self.lx, self.ly][axis]

        return squeeze(fcg)

    def cpsd(self, f, g, fs = None, x0=None, y0=None, Norm = False, **kwargs):
        '''
        Function to calculate the Cross - power Spectral density of 2 signals.
        We are insterested in using this to separate apmplitude, which would give us
        an intuition of the probability distribution; and the phase, which is the most
        used important quantity here. For that reaso, we get the amplitude and phase.
        Also, take into account that if we average the phase, the code will make
        a weighted average, because the phases that contribute more are those
        which have higher probability.
        The default values of it are expected to copy the matlab function.
        '''

        assert array_equal(shape(f), shape(g)), 'The dimensions of f and g should be equal'

        if type(x0) != type(None) and type(y0) == type(None):
            f_cp, g_cp = copy(f[:, x0, :]), copy(g[:, x0, :])
            z, axis    = x0, 1

        elif type(x0) == type(None) and type(y0) != type(None):
            f_cp, g_cp  = transpose(f, (0, 2, 1))[:, y0, :], transpose(g, (0, 2, 1))[:, y0, :]
            z, axis     = y0, 0

        else:
            raise TypeError('One of the variables should be None, the other and int or an array of ints')
        if fs == None:
            fs = 1 / self.dt

        f, PFG = csd(f_cp, g_cp, fs, window = 'hamming', axis = 0, **kwargs)

        ## Normalization
        l   = [self.lx, self.ly][axis]
        if Norm:
            Ampli = absolute(PFG)
            Angle = angle(PFG)
            Amp = self.integrate(Ampli, 1, axis = -1) / l
            Ang = self.integrate(Angle * Ampli, 1, axis = -1) / (Amp * pi * l)

        else:
            PFG = self.integrate(PFG, 1, axis = -1) / l

            Amp = absolute(PFG)
            Ang = angle(PFG)

        return Amp, Ang, f

    def save_matlab(self, variables_dic, name = None, model = None):
        '''
        A function that allow us to save the values we want into a matlab file.
        This was used to compare Python and Matlab functions. As matlab integrate
        function does not allow uneven grids nor integrate over an axis. Same with
        the CPSD function.
        '''

        if type(model) == type(None):
            model = self.model
        if type(name) == type(None):
            name = f'ions_vrad_{model}.mat'

        savemat(name, mdict = variables_dic)

    def perturbation(self, variable, averg_var = None, intervals = None):
        '''
        Take out the trend of a signal to get only the perturbation.
        We shall accept that the variables obtained from simulations can be
        separated into: n = ñ + <n>, where <n> is the average and ñ the perturbation.
        It is important to notice that we are only interested in analysing the
        perturbation ñ.
        '''

        if type(variable) == str:
            perturb = copy(self.Data[variable][:])
        else:
            perturb = copy(variable)

        if type(averg_var) == type(None):
            averg_var = self.integrate(perturb, dim_integral = 1, typ = 'y') / self.ly

        if type(intervals) == type(None):
            return perturb - average(averg_var)

        else:
            for i in range(len(intervals)):
                perturb[intervals[i]:intervals[i + 1]] -= average(averg_var[intervals[i]:intervals[i + 1]])

            return perturb

class units():
    '''
    A class to calculate Kappa and alpha from the characteristics of the tokamaks
    a and R_0 are the minor and major radius in m, B is the magnetic field of
    the coils in T, T_e is the electron temperature in eV and the nucleus is the
    fuel, generally Deuterium D, otherwise give m_i in kg (use scipy.constants
    m_n and m_p for simplicity)
    '''
    def __init__(self, R_0 = None, a = None, B = 1, T_e = 20, nucleus = 'D', m_i = None):
        self.R_0 = R_0; self.a = a; self.B = B
        self.T_e = T_e if T_e >= 1 else T_e / e
        self.m_i = m_p + m_n if nucleus == 'D' else m_i

        self.rho_s    = (self.T_e * self.m_i) ** 0.5 / (self.B)
        self.omega_ci =  e * self.B / (self.m_i)

        self.kappa = self.rho_s / R_0
        self.calculate_alpha()

    def calculate_alpha(self, constant = constant):
        '''
        Calculate alpha as a function of the one use at HESEL
        '''
        self.alpha = constant * (self.R_0 ** -2) * (self.T_e ** (5 / 2)) / self.B

    def m_to_rho_s (self, r):
        '''
        Change from meters to rho_s
        '''
        return r / rho_s
    def rho_s_to_m (self, r):
        '''
        Change from rho_s to meters
        '''
        return r * rho_s

    def eV_to_J (T):
        '''
        Change from eV to Jules
        '''
        return T * e
    def J_to_eV (T):
        '''
        Change from Jules to eV
        '''
        return T / e

    def sec_to_omega_ci (self, t):
        '''
        Change from seconds to omega_ci
        '''
        return t / self.omega_ci
    def omega_ci_to_sec (self, t):
        '''
        Change from omega_ci to seconds
        '''
        return t * self.omega_ci
