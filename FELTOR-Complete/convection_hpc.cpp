#include <iostream>
#include <iomanip>
#include <vector>

#ifdef FELTOR_MPI
#include <mpi.h>
#endif //FELTOR_MPI

#include "dg/file/nc_utilities.h"
#include "dg/algorithm.h"
#include "convection.h"
#include "parameters.h"

#ifdef FELTOR_MPI
using HVec            = dg::MHVec;
using DVec            = dg::MDVec;
using DMatrix         = dg::MDMatrix;
using IDMatrix        = dg::MIDMatrix;
using Grid2d          = dg::MPIGrid2d;
using CartesianGrid2d = dg::CartesianMPIGrid2d;
#define MPI_OUT if(rank==0)
#else //FELTOR_MPI
using HVec            = dg::HVec;
using DVec            = dg::DVec;
using DMatrix         = dg::DMatrix;
using IDMatrix        = dg::IDMatrix;
using Grid2d          = dg::Grid2d;
using CartesianGrid2d = dg::CartesianGrid2d;
#define MPI_OUT
#endif //FELTOR_MPI


int main( int argc, char* argv[])
{
  #ifdef FELTOR_MPI
      ////////////////////////////////setup MPI///////////////////////////////
      int provided;
      MPI_Init_thread( &argc, &argv, MPI_THREAD_FUNNELED, &provided);
      if( provided != MPI_THREAD_FUNNELED)
      {
          std::cerr << "wrong mpi-thread environment provided!\n";
          return -1;
      }
      int periods[2] = {false, true}; //non-, periodic
      int rank, size;
      MPI_Comm_rank( MPI_COMM_WORLD, &rank);
      MPI_Comm_size( MPI_COMM_WORLD, &size);

      int np[2];
      if(rank==0)
      {
          np[0] = atoi(argv[3]);
          np[1] = atoi(argv[4]);
          std::cout << "Computing with "<<np[0]<<" x "<<np[1]<<" = "<<size<<std::endl;
          assert( size == np[0]*np[1]);
      }
      MPI_Bcast( np, 2, MPI_INT, 0, MPI_COMM_WORLD);
      MPI_Comm comm;
      MPI_Cart_create( MPI_COMM_WORLD, 2, np, periods, true, &comm);
      int num_args(5);
  #else
      int num_args(3);
  #endif//FELTOR_MPI-

    //Parameter initialisation
    Json::Value js;
    Json::CharReaderBuilder parser;
    parser["collectComments"] = false;
    std::string errs;

    if( argc != num_args)
    {
        #ifdef FELTOR_MPI
        MPI_OUT std::cerr << "ERROR: Wrong number of arguments!\nUsage: "<< argv[0]<<" [inputfile] [outputfile] [np0] [np1]\n";
        #else
        MPI_OUT std::cerr << "ERROR: Wrong number of arguments!\nUsage: "<< argv[0]<<" [inputfile] [outputfile]\n";
        #endif
        return -1;
    }
    else
    {
        std::ifstream is(argv[1]);
        parseFromStream( parser, is, &js, &errs); //read input without comments
    }
    MPI_OUT std::cout << js<<std::endl;
    const convection::Parameters p( js);
    MPI_OUT p.display( std::cout);


    ////////////////////////////////set up computations///////////////////////////
    Grid2d grid( 0, p.lx, 0, p.ly, p.n, p.Nx, p.Ny, p.bc_x_n, p.bc_y_n
                #ifdef FELTOR_MPI
                , comm
                #endif //FELTOR_MPI
    );
    Grid2d grid_out( 0, p.lx, 0, p.ly, p.n_out, p.Nx_out, p.Ny_out, p.bc_x_n, p.bc_y_n
                    #ifdef FELTOR_MPI
                    , comm
                    #endif //FELTOR_MPI
    );
    //create RHS
  	//exp is the explicit part and imp the implicit. Both defined as
  	//classes form the convection.h file (obviously)
    convection::ExplicitPart< CartesianGrid2d, DMatrix, DVec > exp( grid, p);
    convection::ImplicitPart< CartesianGrid2d, DMatrix, DVec > imp( grid, p);
    //////////////////create initial vector///////////////////////////////////////
    dg::Gaussian g( p.posX*p.lx, p.posY*p.ly, p.sigma, p.sigma, p.amp); //gaussian width is in absolute values
    std::array<DVec,2> y0{
        dg::evaluate(g, grid),
        dg::evaluate(dg::zero,grid) // omega == 0
    };
    {DVec ones(dg::evaluate(dg::one, grid));
    dg::blas1::axpby( p.nb,  ones, 1., y0[0]);}
    //////////////////initialisation of timekarniadakis and first step///////////////////
    double time = 0;
    dg::Karniadakis< std::array<DVec,2> > karniadakis( y0, y0[0].size(), p.eps_time);
    karniadakis.init( exp, imp, time, y0, p.dt);
    /////////////////////////////set up netcdf/////////////////////////////////////
    dg::file::NC_Error_Handle err;
    int ncid;
    MPI_OUT err = nc_create( argv[2],NC_NETCDF4|NC_CLOBBER, &ncid);
    std::string input = js.toStyledString();
    MPI_OUT err = nc_put_att_text( ncid, NC_GLOBAL, "inputfile", input.size(), input.data());
    int dim_ids[3], tvarID;

    MPI_OUT err = dg::file::define_dimensions( ncid, dim_ids, &tvarID, grid_out);

    DVec transfer (dg::evaluate(dg::zero, grid));

    size_t start = 0, count = 1;
    int dataIDs[4];
    std::string names[4] = {"electrons", "ions", "potential", "vorticity"};
    IDMatrix interpolate = dg::create::interpolation( grid_out, grid);
    std::vector<DVec> transferD(4, dg::evaluate(dg::zero, grid_out)); // grid_out
    HVec transferH(dg::evaluate(dg::zero, grid_out)); // grid_out

    //field IDs

    for( unsigned i=0; i<4; i++){
       MPI_OUT err = nc_def_var( ncid, names[i].data(), NC_DOUBLE, 3, dim_ids, &dataIDs[i]);}

    dg::blas2::symv( interpolate, y0[0],           transferD[0]);
    dg::blas2::symv( interpolate, y0[0],           transferD[1]);
    dg::blas2::symv( interpolate, exp.potential(), transferD[2]);
    dg::blas2::symv( interpolate, y0[1],           transferD[3]);

    for( int k=0;k<4; k++)
    {
        dg::assign( transferD[k], transferH);
        dg::file::put_vara_double( ncid, dataIDs[k], start, grid_out, transferH);
    }
    MPI_OUT err = nc_put_vara_double( ncid, tvarID, &start, &count, &time);
    MPI_OUT std::cout << "Exiting the fields" << std::endl;

    ///////////////////////////////////////Timeloop/////////////////////////////////
    const double mass0 = exp.mass(), mass_blob0 = mass0 - grid.lx()*grid.ly();
    dg::Timer t;
    t.tic();
    try
    {
#ifdef DG_BENCHMARK
    unsigned step = 0;
#endif //DG_BENCHMARK

    for( unsigned i=1; i<=p.maxout; i++)
    {

#ifdef DG_BENCHMARK
        dg::Timer ti;
        ti.tic();
#endif//DG_BENCHMARK

        for( unsigned j=0; j<p.itstp; j++)
        {
                karniadakis.step( exp, imp, time, y0);
            //store accuracy details
            {
                MPI_OUT std::cout << "(m_tot-m_0)/m_0: "<< (exp.mass()-mass0)/mass_blob0<<"\t";
            }
        }
        //////////////////////////write fields/////////////////////////
        start = i;
        dg::blas2::symv( interpolate, y0[0], transferD[0]);
        dg::blas2::symv( interpolate, y0[0], transferD[1]);
        dg::blas2::symv( interpolate, exp.potential(), transferD[2]);
        dg::blas2::symv( interpolate, y0[1], transferD[3]);
        MPI_OUT err = nc_open(argv[2], NC_WRITE, &ncid);
        for( int k=0;k<4; k++)
        {
            dg::assign( transferD[k], transferH);
            dg::file::put_vara_double( ncid, dataIDs[k], start, grid_out, transferH);
        }
        MPI_OUT err = nc_put_vara_double( ncid, tvarID, &start, &count, &time);
        MPI_OUT err = nc_close(ncid);

#ifdef DG_BENCHMARK
        ti.toc();
        step+=p.itstp;
        MPI_OUT std::cout << "\n\t Step "<<step <<" of "<<p.itstp*p.maxout <<" at time "<<time;
        MPI_OUT std::cout << "\n\t Average time for one step: "<<ti.diff()/(double)p.itstp<<"s\n\n"<<std::flush;
#endif//DG_BENCHMARK
    }
    }
    catch( dg::Fail& fail) {
        MPI_OUT std::cerr << "CG failed to converge to "<<fail.epsilon()<<"\n";
        MPI_OUT std::cerr << "Does Simulation respect CFL condition?\n";
    }
    t.toc();
    unsigned hour = (unsigned)floor(t.diff()/3600);
    unsigned minute = (unsigned)floor( (t.diff() - hour*3600)/60);
    double second = t.diff() - hour*3600 - minute*60;
    MPI_OUT std::cout << std::fixed << std::setprecision(2) <<std::setfill('0');
    MPI_OUT std::cout <<"Computation Time \t"<<hour<<":"<<std::setw(2)<<minute<<":"<<second<<"\n";
    MPI_OUT std::cout <<"which is         \t"<<t.diff()/p.itstp/p.maxout<<"s/step\n";

    return 0;
}
