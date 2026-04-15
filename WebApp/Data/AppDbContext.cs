using Microsoft.EntityFrameworkCore;
using SmartSecuritySystem.Models;
using WebApp.Models;

namespace WebApp.Data
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options)
            : base(options)
        {
        }

        // =========================
        // USERS
        // =========================
        public DbSet<User> Users { get; set; }

        // =========================
        // LOGIN LOGS ✅ (ADDED FIX)
        // =========================
        public DbSet<LoginLog> LoginLogs { get; set; }

        // =========================
        // ROOMS
        // =========================
        public DbSet<Room> Rooms { get; set; }

        // =========================
        // CAMERAS
        // =========================
        public DbSet<Camera> CameraDevices { get; set; }

        // =========================
        // ALERTS
        // =========================
        public DbSet<Alert> Alerts { get; set; }

        // =========================
        // ACCESS LOGS
        // =========================
        public DbSet<AccessLog> AccessLogs { get; set; }

        // =========================
        // DETECTION LOGS
        // =========================
        public DbSet<DetectionLog> DetectionLogs { get; set; }

        // =========================
        // OCCUPANCY
        // =========================
        public DbSet<RoomOccupancy> RoomOccupancy { get; set; }

        // =========================
        // CONFIGURATION
        // =========================
        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            // ROOMS
            modelBuilder.Entity<Room>()
                .ToTable("rooms");

            // CAMERAS
            modelBuilder.Entity<Camera>()
                .ToTable("camera_devices");

            modelBuilder.Entity<Camera>()
                .Property(c => c.Status)
                .HasDefaultValue("active");

            // ALERTS
            modelBuilder.Entity<Alert>()
                .ToTable("alerts");

            modelBuilder.Entity<Alert>()
                .Property(a => a.Severity)
                .HasConversion<string>();

            modelBuilder.Entity<Alert>()
                .Property(a => a.Status)
                .HasConversion<string>();

            // ACCESS LOGS
            modelBuilder.Entity<AccessLog>()
                .ToTable("access_logs");

            // DETECTION LOGS
            modelBuilder.Entity<DetectionLog>()
                .ToTable("detection_logs");

            // OCCUPANCY
            modelBuilder.Entity<RoomOccupancy>()
                .ToTable("room_occupancy");

            // LOGIN LOGS ✅ (ADDED TABLE MAPPING)
            modelBuilder.Entity<LoginLog>()
                .ToTable("login_logs");
        }
    }
}