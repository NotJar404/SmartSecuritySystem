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
        // DBSets
        // =========================
        public DbSet<User> Users { get; set; }
        public DbSet<LoginLog> LoginLogs { get; set; }
        public DbSet<Room> Rooms { get; set; }
        public DbSet<Camera> CameraDevices { get; set; }
        public DbSet<Alert> Alerts { get; set; }
        public DbSet<AccessLog> AccessLogs { get; set; }
        public DbSet<DetectionLog> DetectionLogs { get; set; }
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

            // =========================
            // ALERTS (IMPORTANT FIX AREA)
            // =========================
            modelBuilder.Entity<Alert>()
                .ToTable("alerts");

            // FIX: store enums as STRING (prevents InvalidCastException)
            modelBuilder.Entity<Alert>()
                .Property(a => a.Type)
                .HasConversion<string>();

            modelBuilder.Entity<Alert>()
                .Property(a => a.Severity)
                .HasConversion<string>();

            modelBuilder.Entity<Alert>()
                .Property(a => a.Status)
                .HasConversion<string>();

            // =========================
            // ACCESS LOGS
            // =========================
            modelBuilder.Entity<AccessLog>()
                .ToTable("access_logs");

            // =========================
            // DETECTION LOGS
            // =========================
            modelBuilder.Entity<DetectionLog>()
                .ToTable("detection_logs");

            // =========================
            // OCCUPANCY
            // =========================
            modelBuilder.Entity<RoomOccupancy>()
                .ToTable("room_occupancy");

            // =========================
            // LOGIN LOGS
            // =========================
            modelBuilder.Entity<LoginLog>()
                .ToTable("login_logs");
        }
    }
}